/*
 * _fsparser: parse FILE_ID_EXTD_DIR_INFO batches into listing columns.
 *
 * Replaces the per-record Python loop in core/fs/local/windows/listing.py.
 * Same validation rules, same output values; records() there is kept as the
 * readable reference the tests compare this module against. The scanner has
 * no Python fallback: the binary is a build requirement.
 *
 * Three entry points share one record decoder:
 *   Columns(link_tags).add(batch) / .entry() / .patch() / .finish(frozen)
 *       the scanner's shape: one batch at a time into C arrays, link
 *       follow-up on the reported indices, one hand-over into exact-size
 *       lists or tuples. One scan worker owns a Columns object from
 *       construction to finish(); it has no lock.
 *   parse_records(batches)
 *       whole directory in one call; reference shape for the gauge only.
 *   parse_batch(batch, *columns)
 *       one batch appended to Python lists; reference shape for the gauge only.
 *
 * Internal module: its interface changes together with listing.py and the
 * committed binary is paired with this source by SHA-256, so there is no
 * version constant. Built against the CPython limited API (3.12+) so one
 * .pyd serves every supported interpreter minor version. Plain portable C.
 */

#define Py_LIMITED_API 0x030C0000
#include <Python.h>

#include <stdint.h>
#include <stdio.h>
#include <string.h>

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
#define FILE_ATTRIBUTE_REPARSE_POINT_BIT 0x400

/* 1601-01-01 to 1970-01-01 in 100 ns units. */
#define FILETIME_EPOCH_DELTA 116444736000000000LL
/* Inside this range (filetime - delta) * 100 cannot overflow int64. */
#define FILETIME_FAST_MIN (INT64_MIN / 100 + FILETIME_EPOCH_DELTA)
#define FILETIME_FAST_MAX (INT64_MAX / 100 + FILETIME_EPOCH_DELTA)

/* Column order of every result: names, is_dir, sizes, mtimes_ns, attributes, created_ns, [identities], reparse_tags. */
#define COLUMN_COUNT 7
enum { COL_NAME, COL_IS_DIR, COL_SIZE, COL_MTIME, COL_ATTRIBUTES, COL_CREATED, COL_TAG };
static const int RESULT_INDEX[COLUMN_COUNT] = {0, 1, 2, 3, 4, 5, 7};
#define RESULT_IDENTITIES 6
#define RESULT_SIZE 8

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

/* ---- Record decoding ---- */

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
	Py_ssize_t name_length = (Py_ssize_t)record->name_length;
	Py_ssize_t next_offset = (Py_ssize_t)record->next_offset;
	if (name_length == 0 || (name_length & 1) != 0
		|| offset + HEADER_SIZE + name_length > length
		|| record->size < 0) {
		*message = "Invalid directory record";
		return 1;
	}
	if (next_offset != 0 && ((next_offset & 7) != 0
		|| next_offset < HEADER_SIZE + name_length
		|| offset + next_offset + HEADER_SIZE > length)) {
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
 * NTFS written by other drivers (ntfs-3g without windows_names) can hold '/',
 * '\\' or NUL in a name; Listing rejects those and the trusted path must too.
 */
static int has_forbidden_character(const record_t *record)
{
	for (uint32_t i = 0; i + 1 < record->name_length; i += 2) {
		if (record->name[i + 1] == 0
			&& (record->name[i] == '/' || record->name[i] == '\\' || record->name[i] == 0)) {
			return 1;
		}
	}
	return 0;
}

/*
 * Validate every record of one batch and count the entries that will be
 * emitted. Returns -1 with `*message` set on malformed input. Pure C; may
 * run without the GIL.
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
			if (has_forbidden_character(&record)) {
				*message = "Invalid directory entry name";
				return -1;
			}
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
	if (filetime >= FILETIME_FAST_MIN && filetime <= FILETIME_FAST_MAX) {
		return PyLong_FromLongLong((filetime - FILETIME_EPOCH_DELTA) * 100);
	}
	PyObject *value = PyLong_FromLongLong(filetime);
	PyObject *epoch = PyLong_FromLongLong(FILETIME_EPOCH_DELTA);
	PyObject *hundred = PyLong_FromLong(100);
	PyObject *delta = NULL;
	PyObject *result = NULL;
	if (value != NULL && epoch != NULL && hundred != NULL) {
		delta = PyNumber_Subtract(value, epoch);
		if (delta != NULL) {
			result = PyNumber_Multiply(delta, hundred);
		}
	}
	Py_XDECREF(value);
	Py_XDECREF(epoch);
	Py_XDECREF(hundred);
	Py_XDECREF(delta);
	return result;
}

/* Create the seven column objects of one record; stops at the first failure and leaks nothing. */
static int make_entry(const record_t *record, PyObject *objects[COLUMN_COUNT])
{
	int byteorder = -1; /* little endian, no BOM handling */
	for (int c = 0; c < COLUMN_COUNT; c++) {
		objects[c] = NULL;
	}
	objects[COL_IS_DIR] = (record->attributes & FILE_ATTRIBUTE_DIRECTORY_BIT) ? Py_True : Py_False;
	Py_INCREF(objects[COL_IS_DIR]);
	if ((objects[COL_NAME] = PyUnicode_DecodeUTF16((const char *)record->name,
			(Py_ssize_t)record->name_length, "surrogatepass", &byteorder)) == NULL
		|| (objects[COL_SIZE] = PyLong_FromLongLong(record->size)) == NULL
		|| (objects[COL_MTIME] = filetime_to_ns(record->modified)) == NULL
		|| (objects[COL_ATTRIBUTES] = PyLong_FromUnsignedLong(record->attributes)) == NULL
		|| (objects[COL_CREATED] = filetime_to_ns(record->created)) == NULL
		|| (objects[COL_TAG] = PyLong_FromUnsignedLong(record->tag)) == NULL) {
		for (int c = 0; c < COLUMN_COUNT; c++) {
			Py_XDECREF(objects[c]);
		}
		return -1;
	}
	return 0;
}

/*
 * Consumer of one parsed entry at absolute index `i`. Takes ownership of
 * the seven objects; `record` gives access to the raw identity and
 * attributes. Returns -1 on failure (objects already released).
 */
typedef int (*store_fn)(void *context, Py_ssize_t i, PyObject *objects[COLUMN_COUNT],
	const record_t *record);

/*
 * Parse one validated batch, storing entries at [base, base + n). Returns the
 * number stored, or -1 with the exception set and `*stored` holding the number
 * of entries the consumer accepted before the failure.
 */
static Py_ssize_t fill_batch(const unsigned char *data, Py_ssize_t length, Py_ssize_t base,
	store_fn store, void *context, Py_ssize_t *stored)
{
	Py_ssize_t offset = 0;
	Py_ssize_t i = base;
	record_t record;
	const char *unused;
	PyObject *objects[COLUMN_COUNT];
	*stored = 0;
	for (;;) {
		if (read_record(data, length, offset, &record, &unused)) {
			PyErr_SetString(PyExc_RuntimeError, "Batch changed during parsing");
			return -1;
		}
		if (!is_dot_entry(&record)) {
			if (make_entry(&record, objects) < 0 || store(context, i, objects, &record) < 0) {
				return -1;
			}
			i++;
			*stored = i - base;
		}
		if (record.next_offset == 0) {
			return i - base;
		}
		offset += record.next_offset;
	}
}

/* ---- Storing into pre-sized Python lists (parse_records, parse_batch) ---- */

typedef struct {
	PyObject *lists[COLUMN_COUNT]; /* each PyList_New(total) */
	char *identities;              /* FILE_ID_SIZE * total bytes */
} list_sink_t;

static int store_into_lists(void *context, Py_ssize_t i, PyObject *objects[COLUMN_COUNT],
	const record_t *record)
{
	list_sink_t *sink = context;
	for (int c = 0; c < COLUMN_COUNT; c++) {
		PyList_SetItem(sink->lists[c], i, objects[c]); /* steals; index is in range */
	}
	memcpy(sink->identities + i * FILE_ID_SIZE, record->identity, FILE_ID_SIZE);
	return 0;
}

static int list_sink_init(list_sink_t *sink, Py_ssize_t total, PyObject **identities_out)
{
	memset(sink, 0, sizeof(*sink));
	for (int c = 0; c < COLUMN_COUNT; c++) {
		sink->lists[c] = PyList_New(total);
		if (sink->lists[c] == NULL) {
			return -1;
		}
	}
	*identities_out = PyBytes_FromStringAndSize(NULL, total * FILE_ID_SIZE);
	if (*identities_out == NULL) {
		return -1;
	}
	sink->identities = PyBytes_AsString(*identities_out);
	return 0;
}

static void list_sink_clear(list_sink_t *sink)
{
	for (int c = 0; c < COLUMN_COUNT; c++) {
		Py_CLEAR(sink->lists[c]);
	}
}

/* Build the 8-tuple result; steals the lists and `identities`. */
static PyObject *build_result(list_sink_t *sink, PyObject *identities)
{
	PyObject *result = PyTuple_New(RESULT_SIZE);
	if (result == NULL) {
		list_sink_clear(sink);
		Py_DECREF(identities);
		return NULL;
	}
	for (int c = 0; c < COLUMN_COUNT; c++) {
		PyTuple_SetItem(result, RESULT_INDEX[c], sink->lists[c]);
		sink->lists[c] = NULL;
	}
	PyTuple_SetItem(result, RESULT_IDENTITIES, identities);
	return result;
}

static int bytes_argument(PyObject *batch, const unsigned char **data, Py_ssize_t *length)
{
	if (!PyBytes_Check(batch)) {
		PyErr_SetString(PyExc_TypeError, "batch must be bytes");
		return -1;
	}
	char *buffer;
	if (PyBytes_AsStringAndSize(batch, &buffer, length) < 0) {
		return -1;
	}
	*data = (const unsigned char *)buffer;
	return 0;
}

/*
 * parse_records(batches) -> (names, is_dir, sizes, mtimes_ns, attributes,
 *                            created_ns, identities, reparse_tags)
 *
 * batches: sequence of bytes, each one GetFileInformationByHandleEx
 *          FileIdExtdDirectoryInfo buffer. Entries "." and ".." are skipped.
 * Validates every batch with the GIL released, then builds seven lists at
 * their final size plus `identities` as bytes of 16 * n.
 * Raises ValueError on malformed input (same messages as the Python parser).
 */
static PyObject *parse_records(PyObject *self, PyObject *batches)
{
	(void)self;
	PyObject *sequence = PySequence_Tuple(batches);
	if (sequence == NULL) {
		return NULL;
	}
	Py_ssize_t batch_count = PyTuple_Size(sequence);
	const unsigned char **data = PyMem_Malloc(sizeof(*data) * (size_t)(batch_count + 1));
	Py_ssize_t *lengths = PyMem_Malloc(sizeof(*lengths) * (size_t)(batch_count + 1));
	PyObject *result = NULL;
	PyObject *identities = NULL;
	list_sink_t sink;
	memset(&sink, 0, sizeof(sink));
	if (data == NULL || lengths == NULL) {
		PyErr_NoMemory();
		goto done;
	}
	for (Py_ssize_t b = 0; b < batch_count; b++) {
		if (bytes_argument(PyTuple_GetItem(sequence, b), &data[b], &lengths[b]) < 0) {
			goto done;
		}
	}

	/* Pass 1: validate and count without the GIL; the bytes are immutable. */
	Py_ssize_t total = 0;
	const char *message = NULL;
	Py_BEGIN_ALLOW_THREADS
	for (Py_ssize_t b = 0; b < batch_count; b++) {
		Py_ssize_t count = count_records(data[b], lengths[b], &message);
		if (count < 0) {
			total = -1;
			break;
		}
		total += count;
	}
	Py_END_ALLOW_THREADS
	if (total < 0) {
		PyErr_SetString(PyExc_ValueError, message);
		goto done;
	}

	/* Pass 2: build the columns. */
	if (list_sink_init(&sink, total, &identities) < 0) {
		goto done;
	}
	Py_ssize_t index = 0;
	for (Py_ssize_t b = 0; b < batch_count; b++) {
		Py_ssize_t stored;
		Py_ssize_t count = fill_batch(data[b], lengths[b], index, store_into_lists, &sink, &stored);
		if (count < 0) {
			goto done;
		}
		index += count;
	}
	result = build_result(&sink, identities);
	identities = NULL;

done:
	list_sink_clear(&sink);
	Py_XDECREF(identities);
	PyMem_Free(data);
	PyMem_Free(lengths);
	Py_DECREF(sequence);
	return result;
}

/*
 * parse_batch(batch, names, is_dir, sizes, mtimes_ns, attributes, created_ns,
 *             identities, reparse_tags) -> count
 *
 * batch: bytes, one FileIdExtdDirectoryInfo buffer. Appends one value per
 * entry to each of the seven lists and 16 bytes per entry to the
 * `identities` bytearray; returns the number appended. Raises ValueError on
 * malformed input and leaves the columns unchanged on any error.
 *
 * Decision (Done/FSParser.md): not integrated. Appending 584-entry batches
 * to Python lists pays CPython's 1.125x list growth: 30.4 ms against 16.8 ms
 * for parse_records and 22.6 ms for Columns at 202,603 entries. Kept so the
 * gauge can keep measuring the three shapes side by side.
 */
static PyObject *parse_batch(PyObject *self, PyObject *args)
{
	(void)self;
	PyObject *batch;
	PyObject *targets[COLUMN_COUNT];
	PyObject *identities;
	if (!PyArg_ParseTuple(args, "SO!O!O!O!O!O!O!O!:parse_batch", &batch,
			&PyList_Type, &targets[COL_NAME], &PyList_Type, &targets[COL_IS_DIR],
			&PyList_Type, &targets[COL_SIZE], &PyList_Type, &targets[COL_MTIME],
			&PyList_Type, &targets[COL_ATTRIBUTES], &PyList_Type, &targets[COL_CREATED],
			&PyByteArray_Type, &identities, &PyList_Type, &targets[COL_TAG])) {
		return NULL;
	}
	const unsigned char *data;
	Py_ssize_t length;
	if (bytes_argument(batch, &data, &length) < 0) {
		return NULL;
	}
	const char *message = NULL;
	Py_ssize_t count = count_records(data, length, &message);
	if (count < 0) {
		PyErr_SetString(PyExc_ValueError, message);
		return NULL;
	}

	Py_ssize_t starts[COLUMN_COUNT];
	for (int c = 0; c < COLUMN_COUNT; c++) {
		starts[c] = PyList_Size(targets[c]);
	}
	Py_ssize_t identity_start = PyByteArray_Size(identities);
	PyObject *result = NULL;
	list_sink_t staging;
	memset(&staging, 0, sizeof(staging));

	/* Fill pre-sized staging lists, then extend the caller's lists once each. */
	for (int c = 0; c < COLUMN_COUNT; c++) {
		staging.lists[c] = PyList_New(count);
		if (staging.lists[c] == NULL) {
			goto done;
		}
	}
	PyObject *returned = PyLong_FromSsize_t(count); /* created before any commit: nothing can fail after */
	if (returned == NULL) {
		goto done;
	}
	if (PyByteArray_Resize(identities, identity_start + count * FILE_ID_SIZE) < 0) {
		Py_DECREF(returned);
		goto undo;
	}
	staging.identities = PyByteArray_AsString(identities) + identity_start;
	Py_ssize_t stored;
	if (fill_batch(data, length, 0, store_into_lists, &staging, &stored) < 0) {
		Py_DECREF(returned);
		goto undo;
	}
	for (int c = 0; c < COLUMN_COUNT; c++) {
		Py_ssize_t size = PyList_Size(targets[c]);
		if (PyList_SetSlice(targets[c], size, size, staging.lists[c]) < 0) {
			Py_DECREF(returned);
			goto undo;
		}
	}
	result = returned;
	goto done;

undo:
	{
		PyObject *exception = PyErr_GetRaisedException();
		for (int c = 0; c < COLUMN_COUNT; c++) {
			Py_ssize_t size = PyList_Size(targets[c]);
			if (size > starts[c]) {
				PyList_SetSlice(targets[c], starts[c], size, NULL);
			}
		}
		PyByteArray_Resize(identities, identity_start);
		PyErr_SetRaisedException(exception);
	}
done:
	list_sink_clear(&staging);
	return result;
}

/* ---- Columns: accumulate into C arrays, hand over once ---- */

#define INITIAL_CAPACITY 1024

typedef struct {
	PyObject_HEAD
	PyObject **columns[COLUMN_COUNT]; /* owned references, `count` filled per column */
	char *identities;                 /* FILE_ID_SIZE * count bytes */
	uint32_t *link_tags;              /* reparse tags that add() reports */
	Py_ssize_t link_tag_count;
	Py_ssize_t count;
	Py_ssize_t capacity;
	int finished;
} columns_object;

/* Release the references of column `c` and its array. */
static void columns_release_column(columns_object *self, int c)
{
	PyObject **array = self->columns[c];
	if (array != NULL) {
		for (Py_ssize_t i = 0; i < self->count; i++) {
			Py_XDECREF(array[i]);
		}
		PyMem_Free(array);
		self->columns[c] = NULL;
	}
}

static void columns_release(columns_object *self)
{
	for (int c = 0; c < COLUMN_COUNT; c++) {
		columns_release_column(self, c);
	}
	PyMem_Free(self->identities);
	self->identities = NULL;
	self->count = 0;
	self->capacity = 0;
}

static int columns_reserve(columns_object *self, Py_ssize_t needed)
{
	if (needed <= self->capacity) {
		return 0;
	}
	Py_ssize_t capacity = self->capacity ? self->capacity : INITIAL_CAPACITY;
	while (capacity < needed) {
		capacity *= 2;
	}
	for (int c = 0; c < COLUMN_COUNT; c++) {
		PyObject **array = PyMem_Realloc(self->columns[c], sizeof(PyObject *) * (size_t)capacity);
		if (array == NULL) {
			PyErr_NoMemory();
			return -1;
		}
		self->columns[c] = array;
	}
	char *identities = PyMem_Realloc(self->identities, (size_t)(capacity * FILE_ID_SIZE));
	if (identities == NULL) {
		PyErr_NoMemory();
		return -1;
	}
	self->identities = identities;
	self->capacity = capacity;
	return 0;
}

typedef struct {
	columns_object *self;
	PyObject *links; /* indices of entries whose reparse tag is one of link_tags */
} columns_sink_t;

static int is_link(const columns_object *self, const record_t *record)
{
	if (!(record->attributes & FILE_ATTRIBUTE_REPARSE_POINT_BIT)) {
		return 0;
	}
	for (Py_ssize_t k = 0; k < self->link_tag_count; k++) {
		if (self->link_tags[k] == record->tag) {
			return 1;
		}
	}
	return 0;
}

static int store_into_arrays(void *context, Py_ssize_t i, PyObject *objects[COLUMN_COUNT],
	const record_t *record)
{
	columns_sink_t *sink = context;
	columns_object *self = sink->self;
	if (is_link(self, record)) {
		PyObject *index = PyLong_FromSsize_t(i);
		int status = index == NULL ? -1 : PyList_Append(sink->links, index);
		Py_XDECREF(index);
		if (status < 0) {
			for (int c = 0; c < COLUMN_COUNT; c++) {
				Py_DECREF(objects[c]);
			}
			return -1;
		}
	}
	for (int c = 0; c < COLUMN_COUNT; c++) {
		self->columns[c][i] = objects[c];
	}
	memcpy(self->identities + i * FILE_ID_SIZE, record->identity, FILE_ID_SIZE);
	return 0;
}

static int columns_check_open(columns_object *self)
{
	if (self->finished) {
		PyErr_SetString(PyExc_ValueError, "Columns already finished");
		return -1;
	}
	return 0;
}

static int columns_check_index(columns_object *self, Py_ssize_t index)
{
	if (index < 0 || index >= self->count) {
		PyErr_SetString(PyExc_IndexError, "Columns index out of range");
		return -1;
	}
	return 0;
}

/*
 * add(batch: bytes) -> list[int]
 * Appends the entries of one batch; returns the absolute indices of entries
 * that are reparse points with one of the constructor's link tags, so the
 * caller can resolve them with entry() and patch() before finish(). Nothing
 * is kept on error.
 */
static PyObject *columns_add(PyObject *object, PyObject *batch)
{
	columns_object *self = (columns_object *)object;
	const unsigned char *data;
	Py_ssize_t length;
	if (columns_check_open(self) < 0 || bytes_argument(batch, &data, &length) < 0) {
		return NULL;
	}
	const char *message = NULL;
	Py_ssize_t count = count_records(data, length, &message);
	if (count < 0) {
		PyErr_SetString(PyExc_ValueError, message);
		return NULL;
	}
	if (columns_reserve(self, self->count + count) < 0) {
		return NULL;
	}
	columns_sink_t sink = {self, PyList_New(0)};
	if (sink.links == NULL) {
		return NULL;
	}
	Py_ssize_t stored;
	if (fill_batch(data, length, self->count, store_into_arrays, &sink, &stored) < 0) {
		for (Py_ssize_t i = self->count; i < self->count + stored; i++) {
			for (int c = 0; c < COLUMN_COUNT; c++) {
				Py_DECREF(self->columns[c][i]);
			}
		}
		Py_DECREF(sink.links);
		return NULL;
	}
	self->count += count;
	return sink.links;
}

/* entry(index) -> (name, attributes, reparse_tag) */
static PyObject *columns_entry(PyObject *object, PyObject *argument)
{
	columns_object *self = (columns_object *)object;
	Py_ssize_t index = PyLong_AsSsize_t(argument);
	if ((index == -1 && PyErr_Occurred()) || columns_check_index(self, index) < 0) {
		return NULL;
	}
	return Py_BuildValue("(OOO)", self->columns[COL_NAME][index],
		self->columns[COL_ATTRIBUTES][index], self->columns[COL_TAG][index]);
}

/*
 * patch(index, is_dir: bool, size: int, mtime_ns: int) -> None
 * Replaces a link's own metadata with its target's. Exact `bool`/`int` and a
 * non-negative size are required: the trusted Listing skips these checks.
 */
static PyObject *columns_patch(PyObject *object, PyObject *args)
{
	columns_object *self = (columns_object *)object;
	Py_ssize_t index;
	PyObject *is_dir, *size, *mtime;
	if (!PyArg_ParseTuple(args, "nO!OO:patch", &index, &PyBool_Type, &is_dir, &size, &mtime)) {
		return NULL;
	}
	if (!PyLong_CheckExact(size) || !PyLong_CheckExact(mtime)) {
		PyErr_SetString(PyExc_TypeError, "size and mtime_ns must be int");
		return NULL;
	}
	if (columns_check_open(self) < 0 || columns_check_index(self, index) < 0) {
		return NULL;
	}
	PyObject *zero = PyLong_FromLong(0);
	if (zero == NULL) {
		return NULL;
	}
	int negative = PyObject_RichCompareBool(size, zero, Py_LT);
	Py_DECREF(zero);
	if (negative < 0) {
		return NULL;
	}
	if (negative) {
		PyErr_SetString(PyExc_ValueError, "Negative file size");
		return NULL;
	}
	PyObject *replacements[3] = {is_dir, size, mtime};
	const int columns[3] = {COL_IS_DIR, COL_SIZE, COL_MTIME};
	for (int k = 0; k < 3; k++) {
		PyObject **slot = &self->columns[columns[k]][index];
		PyObject *previous = *slot;
		Py_INCREF(replacements[k]);
		*slot = replacements[k];
		Py_DECREF(previous);
	}
	Py_RETURN_NONE;
}

/*
 * finish(frozen=False) -> (names, is_dir, sizes, mtimes_ns, attributes,
 *                          created_ns, identities, reparse_tags)
 * Moves every accumulated object into exact-size lists (or tuples when
 * `frozen`). All destinations are allocated before anything moves, so an
 * allocation failure leaves the accumulator exactly as it was; on success the
 * Columns object is empty and rejects further use.
 */
static PyObject *columns_finish(PyObject *object, PyObject *args, PyObject *kwargs)
{
	columns_object *self = (columns_object *)object;
	int frozen = 0;
	static char *keywords[] = {"frozen", NULL};
	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|p:finish", keywords, &frozen)) {
		return NULL;
	}
	if (columns_check_open(self) < 0) {
		return NULL;
	}
	Py_ssize_t count = self->count;
	PyObject *result = PyTuple_New(RESULT_SIZE);
	if (result == NULL) {
		return NULL;
	}
	for (int c = 0; c < COLUMN_COUNT; c++) {
		PyObject *column = frozen ? PyTuple_New(count) : PyList_New(count);
		if (column == NULL) {
			Py_DECREF(result); /* columns with NULL items are safe to free */
			return NULL;
		}
		PyTuple_SetItem(result, RESULT_INDEX[c], column);
	}
	PyObject *identities = PyBytes_FromStringAndSize(
		self->identities ? self->identities : "", count * FILE_ID_SIZE);
	if (identities == NULL) {
		Py_DECREF(result);
		return NULL;
	}
	PyTuple_SetItem(result, RESULT_IDENTITIES, identities);

	/* Nothing below can fail: move the references and free each array as it empties. */
	self->finished = 1;
	for (int c = 0; c < COLUMN_COUNT; c++) {
		PyObject *column = PyTuple_GetItem(result, RESULT_INDEX[c]);
		PyObject **array = self->columns[c];
		for (Py_ssize_t i = 0; i < count; i++) {
			if (frozen) {
				PyTuple_SetItem(column, i, array[i]); /* steals */
			} else {
				PyList_SetItem(column, i, array[i]); /* steals */
			}
		}
		PyMem_Free(array);
		self->columns[c] = NULL;
	}
	columns_release(self);
	return result;
}

static Py_ssize_t columns_length(PyObject *object)
{
	return ((columns_object *)object)->count;
}

static void columns_dealloc(PyObject *object)
{
	columns_object *self = (columns_object *)object;
	columns_release(self);
	PyMem_Free(self->link_tags);
	PyTypeObject *type = Py_TYPE(object);
	freefunc free = (freefunc)PyType_GetSlot(type, Py_tp_free);
	free(object);
	Py_DECREF(type);
}

/* Columns(link_tags): the reparse tags whose entries add() reports for follow-up. */
static PyObject *columns_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
	PyObject *tags;
	static char *keywords[] = {"link_tags", NULL};
	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O:Columns", keywords, &tags)) {
		return NULL;
	}
	PyObject *sequence = PySequence_Tuple(tags);
	if (sequence == NULL) {
		return NULL;
	}
	Py_ssize_t tag_count = PyTuple_Size(sequence);
	uint32_t *link_tags = PyMem_Malloc(sizeof(uint32_t) * (size_t)(tag_count + 1));
	if (link_tags == NULL) {
		Py_DECREF(sequence);
		return PyErr_NoMemory();
	}
	for (Py_ssize_t k = 0; k < tag_count; k++) {
		unsigned long tag = PyLong_AsUnsignedLong(PyTuple_GetItem(sequence, k));
		if ((tag == (unsigned long)-1 && PyErr_Occurred()) || tag > UINT32_MAX) {
			if (!PyErr_Occurred()) {
				PyErr_SetString(PyExc_OverflowError, "link tag does not fit in 32 bits");
			}
			PyMem_Free(link_tags);
			Py_DECREF(sequence);
			return NULL;
		}
		link_tags[k] = (uint32_t)tag;
	}
	Py_DECREF(sequence);
	allocfunc alloc = (allocfunc)PyType_GetSlot(type, Py_tp_alloc);
	columns_object *self = (columns_object *)alloc(type, 0);
	if (self == NULL) {
		PyMem_Free(link_tags);
		return NULL;
	}
	memset(self->columns, 0, sizeof(self->columns));
	self->identities = NULL;
	self->link_tags = link_tags;
	self->link_tag_count = tag_count;
	self->count = 0;
	self->capacity = 0;
	self->finished = 0;
	return (PyObject *)self;
}

static PyMethodDef columns_methods[] = {
	{"add", columns_add, METH_O,
	 "add(batch: bytes) -> list of indices of link entries (reparse points with one of link_tags)"},
	{"entry", columns_entry, METH_O, "entry(index) -> (name, attributes, reparse_tag)"},
	{"patch", columns_patch, METH_VARARGS, "patch(index, is_dir: bool, size: int, mtime_ns: int) -> None"},
	{"finish", (PyCFunction)(void (*)(void))columns_finish, METH_VARARGS | METH_KEYWORDS,
	 "finish(frozen=False) -> (names, is_dir, sizes, mtimes_ns, attributes, created_ns, "
	 "identities, reparse_tags)"},
	{NULL, NULL, 0, NULL}
};

static PyType_Slot columns_slots[] = {
	{Py_tp_new, columns_new},
	{Py_tp_dealloc, columns_dealloc},
	{Py_tp_methods, columns_methods},
	{Py_sq_length, columns_length},
	{Py_tp_doc, "Columns(link_tags): accumulates FILE_ID_EXTD_DIR_INFO batches into listing columns. "
	 "Owned by one thread from construction to finish()."},
	{0, NULL}
};

static PyType_Spec columns_spec = {
	"_fsparser.Columns",
	sizeof(columns_object),
	0,
	Py_TPFLAGS_DEFAULT,
	columns_slots
};

/* ---- Natural sort keys (R10 in Done/FSPaneArch002.md) ---- */

/*
 * Reference: fman.impl.util.natural.natural_key, kept in Python as the
 * specification the tests compare this against:
 *
 *   parts = re.split(r'(\d+)', name.lower())
 *   for each digit run: value digits (unicodedata.decimal), lstrip('0') or '0';
 *     len <= 6  -> '0' + digits.zfill(6)
 *     otherwise -> '1' + '1' * len(str(len)) + '0' + str(len) + digits
 *   return ''.join(parts)
 *
 * re's \d for str is Unicode category Nd, whose members all carry a decimal
 * value in runs of ten. The table lists the first code point of every run.
 */
static const uint32_t DECIMAL_RUN_STARTS[] = {
	0x0030, 0x0660, 0x06F0, 0x07C0, 0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6,
	0x0C66, 0x0CE6, 0x0D66, 0x0DE6, 0x0E50, 0x0ED0, 0x0F20, 0x1040, 0x1090, 0x17E0,
	0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90, 0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620,
	0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10, 0x104A0, 0x10D30, 0x10D40,
	0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0, 0x11650, 0x116C0, 0x116D0,
	0x116DA, 0x11730, 0x118E0, 0x11950, 0x11BF0, 0x11C50, 0x11D50, 0x11DA0, 0x11F50, 0x16130,
	0x16A60, 0x16AC0, 0x16B50, 0x16D70, 0x1CCF0, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6,
	0x1E140, 0x1E2F0, 0x1E4F0, 0x1E5F1, 0x1E950, 0x1FBF0
};
#define DECIMAL_RUN_COUNT (sizeof(DECIMAL_RUN_STARTS) / sizeof(DECIMAL_RUN_STARTS[0]))
#define UNICODE_VERSION "16.0.0"

/* Decimal value 0-9 of `code`, or -1. Binary search over the run starts. */
static int decimal_value(uint32_t code)
{
	if (code < 0x80) {
		return (code >= '0' && code <= '9') ? (int)(code - '0') : -1;
	}
	size_t low = 0, high = DECIMAL_RUN_COUNT;
	while (low < high) {
		size_t middle = (low + high) / 2;
		if (DECIMAL_RUN_STARTS[middle] <= code) {
			low = middle + 1;
		} else {
			high = middle;
		}
	}
	if (low == 0) {
		return -1;
	}
	uint32_t start = DECIMAL_RUN_STARTS[low - 1];
	return code - start < 10 ? (int)(code - start) : -1;
}

/* Growable UCS-4 output buffer reused across keys. */
typedef struct {
	uint32_t *data;
	Py_ssize_t length;
	Py_ssize_t capacity;
} key_buffer_t;

static int key_reserve(key_buffer_t *buffer, Py_ssize_t extra)
{
	if (buffer->length + extra <= buffer->capacity) {
		return 0;
	}
	Py_ssize_t capacity = buffer->capacity ? buffer->capacity : 256;
	while (capacity < buffer->length + extra) {
		capacity *= 2;
	}
	uint32_t *data = PyMem_Realloc(buffer->data, sizeof(uint32_t) * (size_t)capacity);
	if (data == NULL) {
		PyErr_NoMemory();
		return -1;
	}
	buffer->data = data;
	buffer->capacity = capacity;
	return 0;
}

/* Emit one normalised digit run: `digits` holds the values 0-9, `count` of them. */
static int key_emit_digits(key_buffer_t *buffer, const uint8_t *digits, Py_ssize_t count)
{
	Py_ssize_t first = 0;
	while (first < count - 1 && digits[first] == 0) {
		first++;                                   /* lstrip('0') or '0' */
	}
	Py_ssize_t significant = count - first;
	char length_text[24];
	int length_digits = 0;
	if (significant > 6) {
		length_digits = snprintf(length_text, sizeof(length_text), "%lld", (long long)significant);
	}
	if (key_reserve(buffer, 1 + 6 + 1 + 2 * length_digits + significant) < 0) {
		return -1;
	}
	uint32_t *out = buffer->data + buffer->length;
	if (significant <= 6) {
		*out++ = '0';
		for (Py_ssize_t pad = significant; pad < 6; pad++) {
			*out++ = '0';
		}
	} else {
		*out++ = '1';
		for (int k = 0; k < length_digits; k++) {
			*out++ = '1';
		}
		*out++ = '0';
		for (int k = 0; k < length_digits; k++) {
			*out++ = (uint32_t)length_text[k];
		}
	}
	for (Py_ssize_t k = first; k < count; k++) {
		*out++ = (uint32_t)('0' + digits[k]);
	}
	buffer->length = out - buffer->data;
	return 0;
}

/*
 * Append the natural key of the lower-cased code points `text[0..length)`
 * to `buffer`. `digits` is scratch space of at least `length` bytes.
 */
static int key_append(key_buffer_t *buffer, const uint32_t *text, Py_ssize_t length, uint8_t *digits)
{
	Py_ssize_t i = 0;
	while (i < length) {
		int value = decimal_value(text[i]);
		if (value < 0) {
			if (key_reserve(buffer, 1) < 0) {
				return -1;
			}
			buffer->data[buffer->length++] = text[i++];
			continue;
		}
		Py_ssize_t count = 0;
		while (i < length && (value = decimal_value(text[i])) >= 0) {
			digits[count++] = (uint8_t)value;
			i++;
		}
		if (key_emit_digits(buffer, digits, count) < 0) {
			return -1;
		}
	}
	return 0;
}

/* Grow the per-name scratch buffers to hold `length` code points. */
static int scratch_reserve(uint32_t **text, uint8_t **digits, Py_ssize_t *scratch, Py_ssize_t length)
{
	if (length < 1) {
		length = 1; /* PyUnicode_AsUCS4 rejects a NULL buffer even for "" */
	}
	if (length <= *scratch) {
		return 0;
	}
	uint32_t *new_text = PyMem_Realloc(*text, sizeof(uint32_t) * (size_t)length);
	if (new_text == NULL) {
		PyErr_NoMemory();
		return -1;
	}
	*text = new_text;
	uint8_t *new_digits = PyMem_Realloc(*digits, (size_t)length);
	if (new_digits == NULL) {
		PyErr_NoMemory();
		return -1;
	}
	*digits = new_digits;
	*scratch = length;
	return 0;
}

/*
 * natural_keys(names, is_dir, ascending) -> tuple[str]
 *
 * One sort key per entry: '1' or '0' for (is_dir ^ ascending), then
 * natural_key(name). ASCII names are lower-cased in C; others go through
 * str.lower() for Python's exact Unicode case mapping. Equivalent Python:
 *   tuple(('1' if d ^ ascending else '0') + natural_key(n) for n, d in zip(names, is_dir))
 * Caller: core.Name.keys (Done/FSPaneArch002.md R10).
 */
static PyObject *natural_keys(PyObject *self, PyObject *args)
{
	(void)self;
	PyObject *names_in, *is_dir_in;
	int ascending;
	if (!PyArg_ParseTuple(args, "OOp:natural_keys", &names_in, &is_dir_in, &ascending)) {
		return NULL;
	}
	PyObject *names = PySequence_Tuple(names_in);
	if (names == NULL) {
		return NULL;
	}
	PyObject *flags = PySequence_Tuple(is_dir_in);
	if (flags == NULL) {
		Py_DECREF(names);
		return NULL;
	}
	Py_ssize_t count = PyTuple_Size(names);
	PyObject *result = NULL;
	key_buffer_t buffer = {NULL, 0, 0};
	uint32_t *text = NULL;
	uint8_t *digits = NULL;
	Py_ssize_t scratch = 0;
	if (PyTuple_Size(flags) != count) {
		PyErr_SetString(PyExc_ValueError, "names and is_dir differ in length");
		goto done;
	}
	result = PyTuple_New(count);
	if (result == NULL) {
		goto done;
	}
	for (Py_ssize_t i = 0; i < count; i++) {
		PyObject *name = PyTuple_GetItem(names, i);
		if (!PyUnicode_Check(name)) {
			PyErr_SetString(PyExc_TypeError, "names must be str");
			goto fail;
		}
		int is_dir = PyObject_IsTrue(PyTuple_GetItem(flags, i));
		if (is_dir < 0) {
			goto fail;
		}
		Py_ssize_t length = PyUnicode_GetLength(name);
		if (scratch_reserve(&text, &digits, &scratch, length) < 0
			|| PyUnicode_AsUCS4(name, text, length, 0) == NULL) {
			goto fail;
		}
		int ascii = 1;
		for (Py_ssize_t k = 0; k < length; k++) {
			if (text[k] >= 0x80) {
				ascii = 0;
				break;
			}
		}
		if (ascii) {
			/* ASCII: lower-casing is A-Z -> a-z, identical to str.lower(). */
			for (Py_ssize_t k = 0; k < length; k++) {
				if (text[k] >= 'A' && text[k] <= 'Z') {
					text[k] += 32;
				}
			}
		} else {
			PyObject *lowered = PyObject_CallMethod(name, "lower", NULL);
			if (lowered == NULL) {
				goto fail;
			}
			length = PyUnicode_GetLength(lowered);
			if (scratch_reserve(&text, &digits, &scratch, length) < 0
				|| PyUnicode_AsUCS4(lowered, text, length, 0) == NULL) {
				Py_DECREF(lowered);
				goto fail;
			}
			Py_DECREF(lowered);
		}
		buffer.length = 0;
		if (key_reserve(&buffer, 1) < 0) {
			goto fail;
		}
		buffer.data[0] = (is_dir ^ ascending) ? '1' : '0';
		buffer.length = 1;
		if (key_append(&buffer, text, length, digits) < 0) {
			goto fail;
		}
		/* Latin-1 keys (the common case) skip the UTF-32 decoder: pack into bytes. */
		uint32_t widest = 0;
		for (Py_ssize_t k = 0; k < buffer.length; k++) {
			widest |= buffer.data[k];
		}
		PyObject *key;
		if (widest < 0x100) {
			if (scratch_reserve(&text, &digits, &scratch, buffer.length) < 0) {
				goto fail;
			}
			for (Py_ssize_t k = 0; k < buffer.length; k++) {
				digits[k] = (uint8_t)buffer.data[k];
			}
			key = PyUnicode_DecodeLatin1((const char *)digits, buffer.length, NULL);
		} else {
			int byteorder = -1; /* native little endian on Windows */
			key = PyUnicode_DecodeUTF32((const char *)buffer.data,
				buffer.length * (Py_ssize_t)sizeof(uint32_t), "surrogatepass", &byteorder);
		}
		if (key == NULL) {
			goto fail;
		}
		PyTuple_SetItem(result, i, key);
	}
	goto done;

fail:
	Py_CLEAR(result);
done:
	PyMem_Free(buffer.data);
	PyMem_Free(text);
	PyMem_Free(digits);
	Py_DECREF(names);
	Py_DECREF(flags);
	return result;
}

/* ---- Module ---- */

static PyMethodDef methods[] = {
	{"parse_records", parse_records, METH_O,
	 "parse_records(batches) -> (names, is_dir, sizes, mtimes_ns, attributes, "
	 "created_ns, identities, reparse_tags)"},
	{"parse_batch", parse_batch, METH_VARARGS,
	 "parse_batch(batch, names, is_dir, sizes, mtimes_ns, attributes, created_ns, "
	 "identities, reparse_tags) -> count"},
	{"natural_keys", natural_keys, METH_VARARGS,
	 "natural_keys(names, is_dir, ascending) -> tuple of sort keys "
	 "('1'/'0' for is_dir ^ ascending, then the natural key of the lower-cased name)"},
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
	PyObject *type = PyType_FromSpec(&columns_spec);
	if (type == NULL) {
		Py_DECREF(result);
		return NULL;
	}
	int status = PyModule_AddObjectRef(result, "Columns", type);
	Py_DECREF(type);
	if (status < 0 || PyModule_AddIntConstant(result, "HEADER_SIZE", HEADER_SIZE) < 0
		|| PyModule_AddStringConstant(result, "UNICODE_VERSION", UNICODE_VERSION) < 0) {
		Py_DECREF(result);
		return NULL;
	}
	return result;
}
