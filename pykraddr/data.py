"""Download and parse road-name address Korean TXT datasets."""

from __future__ import annotations

import codecs
import io
import os
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from ._http import SessionLike, build_session, raise_for_http_error, response_json, without_none
from .exceptions import KrAddrNoDataError, KrAddrParseError
from .models import DatasetFile, RelatedJibunRecord, RoadNameAddressKoreanRecord

DEFAULT_DATA_BASE_URL = "https://business.juso.go.kr"
ROAD_NAME_KOREAN_DETAIL_SN = "1"

ROAD_NAME_ADDRESS_COLUMNS = (
    "road_address_management_number",
    "legal_dong_code",
    "sido_name",
    "sigungu_name",
    "legal_eup_myeon_dong_name",
    "legal_ri_name",
    "mountain_yn",
    "lot_main_no",
    "lot_sub_no",
    "road_name_code",
    "road_name",
    "underground_yn",
    "building_main_no",
    "building_sub_no",
    "administrative_dong_code",
    "administrative_dong_name",
    "postal_code",
    "previous_road_name_address",
    "effective_date",
    "apartment_yn",
    "change_reason_code",
    "building_register_name",
    "sigungu_building_name",
    "remark",
)
RELATED_JIBUN_COLUMNS = (
    "road_address_management_number",
    "legal_dong_code",
    "sido_name",
    "sigungu_name",
    "legal_eup_myeon_dong_name",
    "legal_ri_name",
    "mountain_yn",
    "lot_main_no",
    "lot_sub_no",
    "road_name_code",
    "underground_yn",
    "building_main_no",
    "building_sub_no",
    "change_reason_code",
)


class RoadNameAddressDataClient:
    """Client for Juso road-name address Korean full and daily TXT downloads."""

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        retries: int = 3,
        base_url: str = DEFAULT_DATA_BASE_URL,
        session: SessionLike | None = None,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.session = session or build_session(retries)

    def list_files(
        self,
        *,
        year: int | str,
        month: int | str,
        data_detail_sn: str = ROAD_NAME_KOREAN_DETAIL_SN,
        expand: bool = False,
    ) -> Mapping[str, Any]:
        """Return the raw file-list response for a data detail and year/month."""

        body = {
            "rtlDtaDtlSn": data_detail_sn,
            "year": str(year),
            "month": int(month),
            "expand": "Y" if expand else "N",
        }
        response = self.session.post(
            f"{self.base_url}/api/jst/selectAttrbDBDwldList",
            json=body,
            headers=_json_headers(),
            timeout=self.timeout,
        )
        raise_for_http_error(response, "selectAttrbDBDwldList")
        payload = response_json(response, "selectAttrbDBDwldList")
        results = payload.get("results")
        if not isinstance(results, Mapping):
            raise KrAddrParseError("selectAttrbDBDwldList: results was not an object")
        return results

    def latest_full_file(
        self,
        *,
        today: date | None = None,
        max_lookback_months: int = 36,
    ) -> DatasetFile:
        """Find the latest available monthly full road-name address Korean ZIP."""

        current = today or date.today()
        year = current.year
        month = current.month
        for _ in range(max_lookback_months):
            results = self.list_files(year=year, month=month)
            candidates = [
                _dataset_file(row, "monthly_full")
                for row in _rows(results.get("allMonthFileList"))
                if _is_existing_file(row)
            ]
            if candidates:
                return max(candidates, key=lambda item: item.standard_date)
            year, month = _previous_month(year, month)
        raise KrAddrNoDataError("no monthly full road-name address Korean file was found")

    def daily_files(
        self,
        *,
        year: int | str,
        month: int | str,
    ) -> list[DatasetFile]:
        """List available daily change files for one month."""

        results = self.list_files(year=year, month=month)
        possible = _rows(results.get("possibleDataList"))
        daily_kind = _daily_kind(possible)
        return [
            _dataset_file(row, "daily", daily_kind=daily_kind)
            for row in _rows(results.get("dayFileList"))
            if _is_existing_file(row)
        ]

    def daily_files_between(self, start: date, end: date) -> list[DatasetFile]:
        """List daily change files whose standard dates are in ``[start, end]``."""

        if end < start:
            return []
        files: list[DatasetFile] = []
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            for file in self.daily_files(year=year, month=month):
                file_date = _yyyymmdd(file.standard_date)
                if file_date is not None and start <= file_date <= end:
                    files.append(file)
            year, month = _next_month(year, month)
        return sorted(files, key=lambda item: item.standard_date)

    def download_file(
        self,
        file: DatasetFile,
        output_dir: str | os.PathLike[str],
        *,
        overwrite: bool = False,
    ) -> Path:
        """Download one advertised dataset file and return the local ZIP path."""

        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        path = output / _safe_file_name(file.file_name or file.real_file_name)
        if path.exists() and not overwrite:
            return path
        params = _download_params(file)
        response = self.session.get(
            f"{self.base_url}/api/jst/download",
            params=params,
            headers={"Referer": f"{self.base_url}/jst/jstAddressDetailsSearch"},
            timeout=self.timeout,
        )
        raise_for_http_error(response, f"download {file.file_name}")
        path.write_bytes(bytes(response.content))
        return path

    def download_latest_full(
        self,
        output_dir: str | os.PathLike[str],
        *,
        today: date | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Discover and download the latest monthly full Korean address ZIP."""

        return self.download_file(
            self.latest_full_file(today=today),
            output_dir,
            overwrite=overwrite,
        )

    def download_daily_changes(
        self,
        output_dir: str | os.PathLike[str],
        *,
        start: date,
        end: date,
        overwrite: bool = False,
    ) -> list[Path]:
        """Download daily change ZIPs for a date range."""

        return [
            self.download_file(file, output_dir, overwrite=overwrite)
            for file in self.daily_files_between(start, end)
        ]


def load_road_name_address_records(
    path: str | os.PathLike[str] | bytes,
    *,
    encoding: str | None = None,
) -> list[RoadNameAddressKoreanRecord]:
    """Load all road-name address Korean records from a TXT or ZIP file."""

    return list(iter_road_name_address_records(path, encoding=encoding))


def iter_road_name_address_records(
    path: str | os.PathLike[str] | bytes,
    *,
    encoding: str | None = None,
) -> Iterator[RoadNameAddressKoreanRecord]:
    """Stream road-name address Korean records from a TXT or ZIP file."""

    for member in _iter_text_members(_content_bytes(path)):
        if _member_kind(member.name) != "road":
            continue
        for line in _iter_decoded_lines(member.content, encoding=encoding):
            if not line.strip():
                continue
            yield _road_record(_split_line(line), source_name=member.name)


def load_related_jibun_records(
    path: str | os.PathLike[str] | bytes,
    *,
    encoding: str | None = None,
) -> list[RelatedJibunRecord]:
    """Load all related-jibun records from a TXT or ZIP file."""

    return list(iter_related_jibun_records(path, encoding=encoding))


def iter_related_jibun_records(
    path: str | os.PathLike[str] | bytes,
    *,
    encoding: str | None = None,
) -> Iterator[RelatedJibunRecord]:
    """Stream related-jibun records from a TXT or ZIP file."""

    for member in _iter_text_members(_content_bytes(path)):
        if _member_kind(member.name) != "jibun":
            continue
        for line in _iter_decoded_lines(member.content, encoding=encoding):
            if not line.strip():
                continue
            yield _related_jibun_record(_split_line(line), source_name=member.name)


def archive_standard_date(path: str | os.PathLike[str]) -> date | None:
    """Infer a daily ``YYYYMMDD`` date from an archive or member name."""

    text = Path(path).name
    parsed = _first_yyyymmdd(text)
    if parsed is not None:
        return parsed
    content = Path(path).read_bytes()
    for member in _iter_text_members(content):
        parsed = _first_yyyymmdd(member.name)
        if parsed is not None:
            return parsed
    return None


def _dataset_file(
    row: Mapping[str, Any],
    period: str,
    *,
    daily_kind: str | None = None,
) -> DatasetFile:
    standard_date = str(row.get("crtrYmd") or row.get("crtrYm") or "").strip()
    request_type = str(row.get("fileTypeNm") or "").strip()
    if period == "daily" and daily_kind:
        request_type = (
            "DC"
            if daily_kind == "ALLRDNM"
            else "DCM"
            if daily_kind == "ALLMTCHG"
            else daily_kind
        )
    file_name = str(row.get("fileNm") or row.get("tmprFileNm") or "").strip()
    real_file_name = str(row.get("tmprFileNm") or row.get("fileNm") or "").strip()
    if not file_name or not real_file_name:
        raise KrAddrParseError("dataset file row did not include a file name")
    registry_year = standard_date[:4]
    return DatasetFile(
        data_detail_sn=str(row.get("RTL_DTA_DTL_SN") or ROAD_NAME_KOREAN_DETAIL_SN),
        data_kind_code=str(row.get("APLY_DTA_SE_CD") or ("22" if period == "daily" else "")),
        data_kind_name=str(row.get("RTL_DTA_CRT_CRTR_KORN_NM") or ""),
        period=period,
        standard_date=standard_date,
        request_type=request_type,
        city_province_code=_optional_text(row.get("ctpvClsfCd")),
        file_name=file_name,
        real_file_name=real_file_name,
        registry_year=registry_year,
        file_sn=str(row.get("fileSn") or "0"),
        attachment_no=str(row.get("atflNo") or "0"),
        raw=row,
    )


def _download_params(file: DatasetFile) -> dict[str, Any]:
    params = {
        "reqType": file.request_type,
        "ctprvnCd": file.city_province_code,
        "stdde": file.standard_date,
        "fileName": file.file_name,
        "realFileName": file.real_file_name,
        "intFileNo": file.file_sn or "0",
        "intNum": file.attachment_no or "0",
        "regYmd": file.registry_year,
    }
    return without_none(params)


def _json_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": DEFAULT_DATA_BASE_URL,
        "Referer": f"{DEFAULT_DATA_BASE_URL}/jst/jstAddressDetailsSearch",
    }


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list) and all(isinstance(row, Mapping) for row in value):
        return value
    raise KrAddrParseError("dataset list value was not a list of objects")


def _is_existing_file(row: Mapping[str, Any]) -> bool:
    has_name = bool(row.get("fileNm") or row.get("tmprFileNm"))
    return str(row.get("isExist") or "").upper() == "Y" and has_name


def _daily_kind(rows: list[Mapping[str, Any]]) -> str | None:
    for row in rows:
        if "22" in str(row.get("APLY_DTA_SE_CD") or ""):
            value = str(row.get("RTL_DTA_CRT_CRTR_ENG_NM") or "").strip()
            if value:
                return value
    return None


def _content_bytes(path: str | os.PathLike[str] | bytes) -> bytes:
    if isinstance(path, bytes):
        return path
    return Path(path).read_bytes()


class _TextMember:
    def __init__(self, name: str, content: bytes) -> None:
        self.name = name
        self.content = content


def _iter_text_members(content: bytes) -> Iterator[_TextMember]:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        yield _TextMember("data.txt", content)
        return
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            lower = name.lower()
            if not (
                lower.endswith((".txt", ".dat"))
                or "th_sgco_rnadr" in lower
                or "rnaddrkor" in lower
            ):
                continue
            yield _TextMember(name, archive.read(name))


def _iter_decoded_lines(content: bytes, *, encoding: str | None) -> Iterator[str]:
    selected = _choose_encoding(content, encoding)
    wrapper = io.TextIOWrapper(io.BytesIO(content), encoding=selected, newline="")
    yield from wrapper


def _choose_encoding(content: bytes, encoding: str | None) -> str:
    candidates: Iterable[str] = (encoding,) if encoding else ("utf-8-sig", "cp949", "euc-kr")
    last_error: UnicodeDecodeError | None = None
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            _validate_decoding(content, candidate)
            return candidate
        except UnicodeDecodeError as exc:
            last_error = exc
    raise KrAddrParseError("TXT encoding could not be decoded") from last_error


def _validate_decoding(content: bytes, encoding: str) -> None:
    decoder = codecs.getincrementaldecoder(encoding)()
    for offset in range(0, len(content), 65536):
        decoder.decode(content[offset : offset + 65536], final=False)
    decoder.decode(b"", final=True)


def _split_line(line: str) -> list[str]:
    return [part.strip() for part in line.rstrip("\r\n").split("|")]


def _road_record(parts: list[str], *, source_name: str) -> RoadNameAddressKoreanRecord:
    if len(parts) < len(ROAD_NAME_ADDRESS_COLUMNS):
        raise KrAddrParseError(
            f"{source_name}: expected {len(ROAD_NAME_ADDRESS_COLUMNS)} fields, got {len(parts)}"
        )
    values = parts[: len(ROAD_NAME_ADDRESS_COLUMNS)]
    return RoadNameAddressKoreanRecord(**dict(zip(ROAD_NAME_ADDRESS_COLUMNS, values, strict=True)))


def _related_jibun_record(parts: list[str], *, source_name: str) -> RelatedJibunRecord:
    if len(parts) < len(RELATED_JIBUN_COLUMNS):
        raise KrAddrParseError(
            f"{source_name}: expected {len(RELATED_JIBUN_COLUMNS)} fields, got {len(parts)}"
        )
    values = parts[: len(RELATED_JIBUN_COLUMNS)]
    return RelatedJibunRecord(**dict(zip(RELATED_JIBUN_COLUMNS, values, strict=True)))


def _member_kind(name: str) -> str:
    lower = name.lower()
    if "lnbr" in lower or "jibun" in lower:
        return "jibun"
    if "mst" in lower or "rnaddrkor" in lower or "rnadr" in lower:
        return "road"
    return "unknown"


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _yyyymmdd(text: str) -> date | None:
    if len(text) != 8 or not text.isdigit():
        return None
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _first_yyyymmdd(text: str) -> date | None:
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
            if len(digits) >= 8:
                parsed = _yyyymmdd(digits[-8:])
                if parsed is not None:
                    return parsed
        else:
            digits = ""
    return None


def _safe_file_name(name: str) -> str:
    keep = []
    for char in name:
        keep.append("_" if char in '<>:"/\\|?*' else char)
    return "".join(keep).strip() or "download.zip"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
