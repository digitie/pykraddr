"use client";

import dynamic from "next/dynamic";
import {
  AlertCircle,
  Building2,
  ChevronLeft,
  ChevronRight,
  Database,
  Layers2,
  ListFilter,
  LocateFixed,
  MapPin,
  RefreshCw,
  Route,
  Search,
  Server,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  SAMPLE_PLACES,
  type AddressPlace,
  splitLegalDongCode,
  splitRoadNameCode,
} from "@/data/address-data";

type SearchScope = "all" | "road" | "jibun" | "code";
type DataMode = "sample" | "postgis";

type KakaoMapPanelProps = {
  places: AddressPlace[];
  selected: AddressPlace;
  showBoundary: boolean;
  showRadius: boolean;
  onSelect: (id: string) => void;
};

type AddressListResponse = {
  items: AddressPlace[];
  page: number;
  page_size: number;
  total: number;
  has_next: boolean;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:3011";
const pageSize = 50;

const KakaoMapPanel = dynamic<KakaoMapPanelProps>(
  () => import("@/components/kakao-map-panel").then((mod) => mod.KakaoMapPanel),
  {
    ssr: false,
    loading: () => <MapLoading />,
  },
);

const scopes: { value: SearchScope; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "road", label: "도로명" },
  { value: "jibun", label: "지번" },
  { value: "code", label: "코드" },
];

const modes: { value: DataMode; label: string; description: string }[] = [
  { value: "sample", label: "샘플 탐색", description: "프론트엔드 검증용 샘플" },
  { value: "postgis", label: "전체 목록", description: "PostGIS 주소 DB" },
];

export function AddressExplorer() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<SearchScope>("all");
  const [mode, setMode] = useState<DataMode>("postgis");
  const [selectedId, setSelectedId] = useState(SAMPLE_PLACES[0].id);
  const [showBoundary, setShowBoundary] = useState(true);
  const [showRadius, setShowRadius] = useState(false);
  const [page, setPage] = useState(1);
  const [serverItems, setServerItems] = useState<AddressPlace[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [serverHasNext, setServerHasNext] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const samplePlaces = useMemo(() => filterPlaces(SAMPLE_PLACES, query, scope), [query, scope]);
  const visiblePlaces = mode === "sample" ? samplePlaces : serverItems;
  const selected =
    visiblePlaces.find((place) => place.id === selectedId) ?? visiblePlaces[0] ?? SAMPLE_PLACES[0];
  const totalCount = mode === "sample" ? samplePlaces.length : serverTotal;

  useEffect(() => {
    if (mode !== "postgis") {
      return;
    }

    const controller = new AbortController();
    async function loadAddresses() {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({
          query,
          scope,
          page: String(page),
          page_size: String(pageSize),
        });
        const response = await fetch(`${apiBaseUrl}/addresses?${params.toString()}`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`주소 API 응답 오류: ${response.status}`);
        }
        const payload = (await response.json()) as AddressListResponse;
        setServerItems(payload.items);
        setServerTotal(payload.total);
        setServerHasNext(payload.has_next);
      } catch (caught) {
        if (controller.signal.aborted) {
          return;
        }
        setServerItems([]);
        setServerTotal(0);
        setServerHasNext(false);
        setError(caught instanceof Error ? caught.message : "주소 API를 불러오지 못했습니다.");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadAddresses();
    return () => controller.abort();
  }, [mode, page, query, scope]);

  const updateQuery = (value: string) => {
    setQuery(value);
    setPage(1);
  };

  const updateScope = (value: SearchScope) => {
    setScope(value);
    setPage(1);
  };

  const updateMode = (value: DataMode) => {
    setMode(value);
    setPage(1);
    setSelectedId(SAMPLE_PLACES[0].id);
  };

  return (
    <main className="min-h-screen bg-[#f7f8fb] text-[#182033]">
      <div className="mx-auto flex min-h-screen w-full max-w-[1480px] flex-col px-4 py-4 sm:px-5 lg:px-6">
        <header className="flex flex-col gap-4 border-b border-[#d9dfeb] pb-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#163b53] text-white shadow-sm">
              <MapPin aria-hidden="true" size={22} strokeWidth={2.2} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-normal text-[#111827]">주소 탐색</h1>
              <p className="mt-0.5 text-sm font-medium text-[#607086]">
                PostgreSQL + PostGIS 기반 주소 브라우저
              </p>
            </div>
          </div>

          <div className="grid gap-2 lg:grid-cols-[auto_minmax(280px,440px)_auto] xl:min-w-[900px]">
            <div className="flex h-11 items-center rounded-lg border border-[#cfd7e5] bg-white p-1">
              {modes.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => updateMode(item.value)}
                  title={item.description}
                  className={`h-9 rounded-md px-3 text-sm font-semibold transition ${
                    mode === item.value
                      ? "bg-[#163b53] text-white shadow-sm"
                      : "text-[#4c5d72] hover:bg-[#eef3f7]"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <label className="relative block">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#6f7f91]"
                size={18}
              />
              <input
                value={query}
                onChange={(event) => updateQuery(event.target.value)}
                className="h-11 w-full rounded-lg border border-[#cfd7e5] bg-white pl-10 pr-3 text-[15px] font-medium text-[#182033] outline-none transition focus:border-[#2b7a78] focus:ring-4 focus:ring-[#2b7a78]/15"
                placeholder="도로명, 지번, 법정동코드, PNU"
                type="search"
              />
            </label>
            <div className="flex h-11 items-center rounded-lg border border-[#cfd7e5] bg-white p-1">
              {scopes.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => updateScope(item.value)}
                  className={`h-9 rounded-md px-3 text-sm font-semibold transition ${
                    scope === item.value
                      ? "bg-[#163b53] text-white shadow-sm"
                      : "text-[#4c5d72] hover:bg-[#eef3f7]"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        <section className="grid flex-1 gap-4 py-4 lg:grid-cols-[430px_minmax(0,1fr)]">
          <aside className="flex min-h-[620px] flex-col gap-4">
            <div className="rounded-lg border border-[#d9dfeb] bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-[#39485c]">
                  {mode === "postgis" ? (
                    <Server aria-hidden="true" size={18} />
                  ) : (
                    <ListFilter aria-hidden="true" size={18} />
                  )}
                  {mode === "postgis" ? "전체 주소 목록" : "샘플 검색 결과"}
                </div>
                <span className="font-mono text-sm font-semibold text-[#0f766e]">
                  {totalCount.toLocaleString("ko-KR")}
                </span>
              </div>

              {error ? (
                <div className="mt-4 flex items-start gap-2 rounded-lg border border-[#f3c8bf] bg-[#fff7f5] px-3 py-3 text-sm font-semibold text-[#a33a25]">
                  <AlertCircle aria-hidden="true" className="mt-0.5 shrink-0" size={17} />
                  <span>{error}</span>
                </div>
              ) : null}

              <div className="mt-4 space-y-2">
                {loading ? <LoadingRows /> : null}
                {!loading && visiblePlaces.length > 0
                  ? visiblePlaces.map((place) => (
                      <ResultRow
                        key={place.id}
                        place={place}
                        selected={place.id === selected.id}
                        onSelect={setSelectedId}
                      />
                    ))
                  : null}
                {!loading && visiblePlaces.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-[#cfd7e5] bg-[#f9fbfd] px-4 py-8 text-center text-sm font-medium text-[#6f7f91]">
                    일치하는 주소 없음
                  </div>
                ) : null}
              </div>

              {mode === "postgis" ? (
                <Pagination
                  page={page}
                  total={serverTotal}
                  hasNext={serverHasNext}
                  loading={loading}
                  onPrevious={() => setPage((value) => Math.max(1, value - 1))}
                  onNext={() => setPage((value) => value + 1)}
                  onRefresh={() => setPage((value) => value)}
                />
              ) : null}
            </div>

            <AddressDetail selected={selected} />
          </aside>

          <section className="flex min-h-[620px] flex-col overflow-hidden rounded-lg border border-[#d9dfeb] bg-white shadow-sm">
            <div className="flex flex-col gap-3 border-b border-[#d9dfeb] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <LocateFixed aria-hidden="true" size={19} className="text-[#0f766e]" />
                <div>
                  <h2 className="text-base font-semibold text-[#111827]">{selected.title}</h2>
                  <p className="font-mono text-xs font-semibold text-[#607086]">
                    {selected.coordinate.lat.toFixed(5)}, {selected.coordinate.lng.toFixed(5)}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <LayerToggle
                  checked={showBoundary}
                  label="경계"
                  onChange={() => setShowBoundary((value) => !value)}
                />
                <LayerToggle
                  checked={showRadius}
                  label="반경"
                  onChange={() => setShowRadius((value) => !value)}
                />
              </div>
            </div>

            <KakaoMapPanel
              places={visiblePlaces.length > 0 ? visiblePlaces : SAMPLE_PLACES}
              selected={selected}
              showBoundary={showBoundary}
              showRadius={showRadius}
              onSelect={setSelectedId}
            />
          </section>
        </section>
      </div>
    </main>
  );
}

function ResultRow({
  place,
  selected,
  onSelect,
}: {
  place: AddressPlace;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(place.id)}
      className={`grid w-full grid-cols-[1fr_auto] gap-3 rounded-lg border px-3 py-3 text-left transition ${
        selected
          ? "border-[#2b7a78] bg-[#edf8f6] shadow-sm"
          : "border-[#e2e7ef] bg-white hover:border-[#b9c7d7] hover:bg-[#f7fafc]"
      }`}
    >
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-[#142033]">{place.title}</span>
          <span className="rounded bg-[#edf0f5] px-1.5 py-0.5 text-[11px] font-bold text-[#536579]">
            {place.category === "road" ? "도로명" : "지번"}
          </span>
        </span>
        <span className="mt-1 block truncate text-sm font-medium text-[#3d4d62]">
          {place.roadAddress}
        </span>
        <span className="mt-1 block truncate font-mono text-xs font-semibold text-[#7a8797]">
          {place.legalDongCode} · {place.pnu}
        </span>
      </span>
      <ChevronRight
        aria-hidden="true"
        className={selected ? "text-[#0f766e]" : "text-[#a2adbc]"}
        size={18}
      />
    </button>
  );
}

function AddressDetail({ selected }: { selected: AddressPlace }) {
  const legal = splitLegalDongCode(selected.legalDongCode);
  const road = splitRoadNameCode(selected.roadNameCode);
  const rows = [
    ["법정동", selected.legalDongCode],
    ["시도", legal.sidoCode],
    ["시군구", legal.sigunguCode],
    ["읍면동", legal.eupMyeonDongCode],
    ["리", legal.riCode],
    ["도로명", selected.roadNameCode],
    ["도로 시군구", road.sigunguCode],
    ["도로번호", road.roadNumber],
    ["PNU", selected.pnu],
    ["경계", selected.boundaryName ?? ""],
    ["좌표 출처", selected.coordinateSource ?? ""],
  ].filter(([, value]) => value);

  return (
    <div className="rounded-lg border border-[#d9dfeb] bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#39485c]">
        <Database aria-hidden="true" size={18} />
        주소 코드
      </div>

      <dl className="mt-4 grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-xs font-bold text-[#6f7f91]">{label}</dt>
            <dd className="truncate font-mono text-xs font-semibold text-[#182033]">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 border-t border-[#e2e7ef] pt-4">
        <div className="flex items-start gap-2">
          <Route aria-hidden="true" className="mt-0.5 text-[#d97706]" size={17} />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-[#142033]">{selected.roadAddress}</p>
            <p className="mt-1 truncate text-sm font-medium text-[#607086]">
              {selected.jibunAddress}
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {selected.tags.map((tag) => (
            <span
              key={tag}
              className="rounded bg-[#eef3f7] px-2 py-1 text-xs font-bold text-[#536579]"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Pagination({
  page,
  total,
  hasNext,
  loading,
  onPrevious,
  onNext,
  onRefresh,
}: {
  page: number;
  total: number;
  hasNext: boolean;
  loading: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onRefresh: () => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="mt-4 flex items-center justify-between border-t border-[#e2e7ef] pt-4">
      <div className="font-mono text-xs font-semibold text-[#607086]">
        {page.toLocaleString("ko-KR")} / {totalPages.toLocaleString("ko-KR")}
      </div>
      <div className="flex items-center gap-2">
        <IconButton disabled={loading || page <= 1} label="이전" onClick={onPrevious}>
          <ChevronLeft aria-hidden="true" size={17} />
        </IconButton>
        <IconButton disabled={loading} label="새로고침" onClick={onRefresh}>
          <RefreshCw aria-hidden="true" size={16} />
        </IconButton>
        <IconButton disabled={loading || !hasNext} label="다음" onClick={onNext}>
          <ChevronRight aria-hidden="true" size={17} />
        </IconButton>
      </div>
    </div>
  );
}

function IconButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: React.ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#d6dee8] bg-white text-[#4c5d72] transition hover:bg-[#f4f7fb] disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function LayerToggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={checked}
      onClick={onChange}
      className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-semibold transition ${
        checked
          ? "border-[#2b7a78] bg-[#edf8f6] text-[#0f766e]"
          : "border-[#d6dee8] bg-white text-[#607086] hover:bg-[#f4f7fb]"
      }`}
    >
      <Layers2 aria-hidden="true" size={16} />
      {label}
    </button>
  );
}

function LoadingRows() {
  return (
    <>
      {Array.from({ length: 5 }, (_, index) => (
        <div
          key={index}
          className="h-[82px] animate-pulse rounded-lg border border-[#e2e7ef] bg-[#f5f8fb]"
        />
      ))}
    </>
  );
}

function MapLoading() {
  return (
    <div className="flex flex-1 items-center justify-center bg-[#eef3f7]">
      <div className="flex items-center gap-3 rounded-lg border border-[#d9dfeb] bg-white px-4 py-3 text-sm font-semibold text-[#536579] shadow-sm">
        <Building2 aria-hidden="true" size={18} />
        지도 로딩
      </div>
    </div>
  );
}

function filterPlaces(places: AddressPlace[], query: string, scope: SearchScope) {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);

  return places.filter((place) => {
    const haystack = scopedText(place, scope);
    return terms.every((term) => haystack.includes(term));
  });
}

function scopedText(place: AddressPlace, scope: SearchScope) {
  if (scope === "road") {
    return `${place.title} ${place.roadAddress}`.toLowerCase();
  }
  if (scope === "jibun") {
    return `${place.title} ${place.jibunAddress}`.toLowerCase();
  }
  if (scope === "code") {
    return `${place.legalDongCode} ${place.roadNameCode} ${place.pnu} ${place.postalCode}`.toLowerCase();
  }
  return [
    place.title,
    place.roadAddress,
    place.jibunAddress,
    place.legalDongCode,
    place.roadNameCode,
    place.pnu,
    place.postalCode,
    ...place.tags,
  ]
    .join(" ")
    .toLowerCase();
}
