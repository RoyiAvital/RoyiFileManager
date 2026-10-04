/*
 * _fsparser: parse FILE_ID_EXTD_DIR_INFO buffers into listing columns.
 *
 * Replaces the per-record Python loop in core/fs/local/windows/listing.py.
 * Same validation rules, same output values; the Python implementation stays
 * as the fallback when this module is unavailable.
 *
 * Built against the CPython limited API (3.12+) so one .pyd serves every
 * supported interpreter minor version. Plain portable C; no intrinsics.
 */

#define Py_LIMITED_API 0x030C0000
#include <Python.h>

#include <stdint.h>
#include <string.h>

#define API_VERSION 1

/* FILE_ID_EXTD_DIR_INFO fixed header: 88 bytes, followed by FileName (UTF-16LE). */
#define HEADER_SIZE 88
#define OFFSET_NEXT_ENTRY 0
#define OFFSET_CREATION_TIME 8
#define OFFSET_LAST_WRITE_TIME 24
#define OFFSET_END_OF_FILE 40
#define OFFSET_FILE_ATTRIBUTES 56
#define OFFSET_FILE_NAME_LENGTH 60
#define OFFSET_REPARSE_TAG 68
#define OFFSET_FILE_ID 72
#define FILE_ID_SIZE 16
#define FILE_ATTRIBUTE_DIRECTORY_BIT 0x10

/* 1601-01-01 to 1970-01-01 in 100 ns units. */
#define FILETIME_EPOCH_DELTA 116444736000000000LL

typedef struct {
	uint32_t next_offset;
	int64_t created;
	int64_t modified;
	int64_t size;
	uint32_t attributes;
	uint32_t name_length;   /* bytes */
	uint32_t tag;
	const unsigned char *identity;
	const unsigned char *name; /* UTF-16LE, name_length bytes */
} record_t;

static uint32_t read_u32(const unsigned char *data)
{
	uint32_t value;
	memcpy(&value, data, sizeof(value));
	return value;
}

static int64_t read_i64(const unsigned char *data)
{
	int64_t value;
	memcpy(&value, data, sizeof(value));
	return value;
}

/*
 * Decode one record at `offset`. Returns 0 on success, 1 on a malformed
 * buffer with `*message` set. Mirrors records() in listing.py exactly.
 */
static int read_record(const unsigned char *data, Py_ssize_t length, Py_ssize_t offset,
	record_t *record, const char **message)
{
	if (offset + HEADER_SIZE > length) {
		*message = "Truncated directory record";
		return 1;
	}
	const unsigned char *header = data + offset;
	record->next_offset = read_u32(header + OFFSET_NEXT_ENTRY);
	record->created = read_i64(header + OFFSET_CREATION_TIME);
	record->modified = read_i64(header + OFFSET_LAST_WRITE_TIME);
	record->size = read_i64(header + OFFSET_END_OF_FILE);
	record->attributes = read_u32(header + OFFSET_FILE_ATTRIBUTES);
	record->name_length = read_u32(header + OFFSET_FILE_NAME_LENGTH);
	record->tag = read_u32(header + OFFSET_REPARSE_TAG);
	record->identity = header + OFFSET_FILE_ID;
	record->name = header + HEADER_SIZE;
	if (record->name_length == 0 || (record->name_length & 1) != 0
		|| offset + HEADER_SIZE + (Py_ssize_t)record->name_length > length
		|| record->size < 0) {
		*message = "Invalid directory record";
		return 1;
	}
	if (record->next_offset != 0 && ((record->next_offset & 7) != 0
		|| record->next_offset < HEADER_SIZE + record->name_length
		|| offset + (Py_ssize_t)record->next_offset + HEADER_SIZE > length)) {
		*message = "Invalid directory record offset";
		return 1;
	}
	return 0;
}

/* "." or ".." in UTF-16LE. */
static int is_dot_entry(const record_t *record)
{
	if (record->name_length == 2) {
		return record->name[0] == '.' && record->name[1] == 0;
	}
	if (record->name_length == 4) {
		return record->name[0] == '.' && record->name[1] == 0
			&& record->name[2] == '.' && record->name[3] == 0;
	}
	return 0;
}

/*
 * Pass 1, GIL released: validate every record of one buffer and count the
 * entries that will be emitted. Returns -1 with `*message` set on error.
 */
static Py_ssize_t count_records(const unsigned char *data, Py_ssize_t length, const char **message)
{
	Py_ssize_t offset = 0;
	Py_ssize_t count = 0;
	record_t record;
	for (;;) {
		if (read_record(data, length, offset, &record, message)) {
			return -1;
		}
		if (!is_dot_entry(&record)) {
			count++;
		}
		if (record.next_offset == 0) {
			return count;
		}
		offset += record.next_offset;
	}
}

/* (filetime - epoch) * 100 as a Python int, exact for every 64-bit input. */
static PyObject *filetime_to_ns(int64_t filetime)
{
	int64_t delta = filetime - FILETIME_EPOCH_DELTA;
	if (delta <= INT64_MAX / 100 && delta >= INT64_MIN / 100) {
		return PyLong_FromLongLong(delta * 100);
	}
	PyObject *big = PyLong_FromLongLong(delta);
	if (big == NULL) {
		return NULL;
	}
	PyObject *hundred = PyLong_FromLong(100);
	if (hundred == NULL) {
		Py_DECREF(big);
		return NULL;
	}
	PyObject *result = PyNumber_Multiply(big, hundred);
	Py_DECREF(big);
	Py_DECREF(hundred);
	return result;
}

typedef struct {
	PyObject *names;
	PyObject *is_dir;
	PyObject *sizes;
	PyObject *mtimes;
	PyObject *attributes;
	PyObject *created;
	PyObject *identities;
	PyObject *tags;
	char *identity_bytes;
} columns_t;

/*
 * Pass 2, GIL held: create the Python objects for one buffer, writing from
 * `*index`. The buffer was validated in pass 1, so no error is possible here
 * except allocation failure.
 */
static int fill_records(const unsigned char *data, Py_ssize_t length, columns_t *columns,
	Py_ssize_t *index)
{
	Py_ssize_t offset = 0;
	record_t record;
	const char *unused;
	for (;;) {
		if (read_record(data, length, offset, &record, &unused)) {
			PyErr_SetString(PyExc_RuntimeError, "Directory buffer changed between passes");
			return -1;
		}
		if (!is_dot_entry(&record)) {
			Py_ssize_t i = *index;
			int byteorder = -1; /* little endian, no BOM handling */
			PyObject *name = PyUnicode_DecodeUTF16((const char *)record.name,
				(Py_ssize_t)record.name_length, "surrogatepass", &byteorder);
			if (name == NULL || PyList_SetItem(columns->names, i, name) < 0) {
				return -1;
			}
			PyObject *is_dir = (record.attributes & FILE_ATTRIBUTE_DIRECTORY_BIT) ? Py_True : Py_False;
			Py_INCREF(is_dir);
			if (PyList_SetItem(columns->is_dir, i, is_dir) < 0) {
				return -1;
			}
			PyObject *size = PyLong_FromLongLong(record.size);
			if (size == NULL || PyList_SetItem(columns->sizes, i, size) < 0) {
				return -1;
			}
			PyObject *modified = filetime_to_ns(record.modified);
			if (modified == NULL || PyList_SetItem(columns->mtimes, i, modified) < 0) {
				return -1;
			}
			PyObject *attributes = PyLong_FromUnsignedLong(record.attributes);
			if (attributes == NULL || PyList_SetItem(columns->attributes, i, attributes) < 0) {
				return -1;
			}
			PyObject *created = filetime_to_ns(record.created);
			if (created == NULL || PyList_SetItem(columns->created, i, created) < 0) {
				return -1;
			}
			PyObject *tag = PyLong_FromUnsignedLong(record.tag);
			if (tag == NULL || PyList_SetItem(columns->tags, i, tag) < 0) {
				return -1;
			}
			memcpy(columns->identity_bytes + i * FILE_ID_SIZE, record.identity, FILE_ID_SIZE);
			*index = i + 1;
		}
		if (record.next_offset == 0) {
			return 0;
		}
		offset += record.next_offset;
	}
}

static void release_buffers(Py_buffer *views, Py_ssize_t count)
{
	for (Py_ssize_t i = 0; i < count; i++) {
		PyBuffer_Release(&views[i]);
	}
	PyMem_Free(views);
}

static void clear_columns(columns_t *columns)
{
	Py_XDECREF(columns->names);
	Py_XDECREF(columns->is_dir);
	Py_XDECREF(columns->sizes);
	Py_XDECREF(columns->mtimes);
	Py_XDECREF(columns->attributes);
	Py_XDECREF(columns->created);
	Py_XDECREF(columns->identities);
	Py_XDECREF(columns->tags);
}

/*
 * parse_records(buffers) -> (names, is_dir, sizes, mtimes_ns, attributes,
 *                            created_ns, identities, reparse_tags)
 *
 * buffers: sequence of bytes-like objects, each one GetFileInformationByHandleEx
 *          FileIdExtdDirectoryInfo batch. Entries "." and ".." are skipped.
 * Returns eight lists of equal length plus `identities` as bytes of 16 * n.
 * Raises ValueError on malformed input (same messages as the Python parser).
 */
static PyObject *parse_records(PyObject *self, PyObject *buffers)
{
	(void)self;
	PyObject *sequence = PySequence_List(buffers);
	if (sequence == NULL) {
		return NULL;
	}
	Py_ssize_t buffer_count = PyList_Size(sequence);
	Py_buffer *views = PyMem_Malloc(sizeof(Py_buffer) * (size_t)(buffer_count > 0 ? buffer_count : 1));
	if (views == NULL) {
		Py_DECREF(sequence);
		return PyErr_NoMemory();
	}
	Py_ssize_t acquired = 0;
	for (; acquired < buffer_count; acquired++) {
		PyObject *item = PyList_GetItem(sequence, acquired); /* borrowed */
		if (PyObject_GetBuffer(item, &views[acquired], PyBUF_SIMPLE) < 0) {
			release_buffers(views, acquired);
			Py_DECREF(sequence);
			return NULL;
		}
	}

	/* Pass 1: validate and count without the GIL. */
	Py_ssize_t total = 0;
	const char *message = NULL;
	Py_BEGIN_ALLOW_THREADS
	for (Py_ssize_t b = 0; b < buffer_count; b++) {
		Py_ssize_t count = count_records(views[b].buf, views[b].len, &message);
		if (count < 0) {
			total = -1;
			break;
		}
		total += count;
	}
	Py_END_ALLOW_THREADS
	if (total < 0) {
		release_buffers(views, buffer_count);
		Py_DECREF(sequence);
		PyErr_SetString(PyExc_ValueError, message);
		return NULL;
	}

	/* Pass 2: build the columns. */
	columns_t columns;
	memset(&columns, 0, sizeof(columns));
	columns.names = PyList_New(total);
	columns.is_dir = PyList_New(total);
	columns.sizes = PyList_New(total);
	columns.mtimes = PyList_New(total);
	columns.attributes = PyList_New(total);
	columns.created = PyList_New(total);
	columns.tags = PyList_New(total);
	columns.identities = PyBytes_FromStringAndSize(NULL, total * FILE_ID_SIZE);
	if (columns.names == NULL || columns.is_dir == NULL || columns.sizes == NULL
		|| columns.mtimes == NULL || columns.attributes == NULL || columns.created == NULL
		|| columns.tags == NULL || columns.identities == NULL) {
		goto fail;
	}
	columns.identity_bytes = PyBytes_AsString(columns.identities);
	if (columns.identity_bytes == NULL) {
		goto fail;
	}
	Py_ssize_t index = 0;
	for (Py_ssize_t b = 0; b < buffer_count; b++) {
		if (fill_records(views[b].buf, views[b].len, &columns, &index) < 0) {
			goto fail;
		}
	}
	if (index != total) {
		PyErr_SetString(PyExc_RuntimeError, "Directory record count changed between passes");
		goto fail;
	}
	release_buffers(views, buffer_count);
	Py_DECREF(sequence);
	PyObject *result = PyTuple_New(8);
	if (result == NULL) {
		clear_columns(&columns);
		return NULL;
	}
	/* PyTuple_SetItem steals each reference; the columns struct no longer owns them. */
	PyTuple_SetItem(result, 0, columns.names);
	PyTuple_SetItem(result, 1, columns.is_dir);
	PyTuple_SetItem(result, 2, columns.sizes);
	PyTuple_SetItem(result, 3, columns.mtimes);
	PyTuple_SetItem(result, 4, columns.attributes);
	PyTuple_SetItem(result, 5, columns.created);
	PyTuple_SetItem(result, 6, columns.identities);
	PyTuple_SetItem(result, 7, columns.tags);
	return result;

fail:
	release_buffers(views, buffer_count);
	Py_DECREF(sequence);
	clear_columns(&columns);
	return NULL;
}

static PyMethodDef methods[] = {
	{"parse_records", parse_records, METH_O,
	 "parse_records(buffers) -> (names, is_dir, sizes, mtimes_ns, attributes, "
	 "created_ns, identities, reparse_tags)"},
	{NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
	PyModuleDef_HEAD_INIT,
	"_fsparser",
	"Native parser for Windows FILE_ID_EXTD_DIR_INFO directory batches.",
	0,
	methods,
	NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit__fsparser(void)
{
	PyObject *result = PyModule_Create(&module);
	if (result == NULL) {
		return NULL;
	}
	if (PyModule_AddIntConstant(result, "API_VERSION", API_VERSION) < 0
		|| PyModule_AddIntConstant(result, "HEADER_SIZE", HEADER_SIZE) < 0) {
		Py_DECREF(result);
		return NULL;
	}
	return result;
}
