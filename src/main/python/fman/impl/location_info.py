from fman.listing import LocationInfo, NATIVE_LOCAL, NETWORK, UNKNOWN


def native_local_scope(location, listing):
	return bool(listing is not None and listing.location == location and
		location.startswith('file://') and not location[7:].startswith(('/', '\\')) and
		listing.scope != (0, bytes(16)))


def location_info(location, listing):
	if listing is None or listing.location != location:
		return None
	if location.startswith(('network://', 'file:////', 'file://\\\\')):
		hint = NETWORK
	elif native_local_scope(location, listing):
		hint = NATIVE_LOCAL
	else:
		hint = UNKNOWN
	return LocationInfo(location, hint)