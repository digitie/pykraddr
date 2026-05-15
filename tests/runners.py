from __future__ import annotations

from kraddr.geo.parser import (
    parse_coordinates_response,
    parse_detail_addresses_response,
    parse_english_search_response,
    parse_search_response,
)
from kraddr.geo.processor import (
    process_coordinates_response,
    process_detail_addresses_response,
    process_english_search_response,
    process_search_response,
)

RUNNERS = {
    "search": {
        "parse": parse_search_response,
        "process": process_search_response,
    },
    "search_english": {
        "parse": parse_english_search_response,
        "process": process_english_search_response,
    },
    "coordinates": {
        "parse": parse_coordinates_response,
        "process": process_coordinates_response,
    },
    "detail_addresses": {
        "parse": parse_detail_addresses_response,
        "process": process_detail_addresses_response,
    },
}
