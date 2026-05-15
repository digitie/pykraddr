# python-kraddr-geo 웹 UI

`web` 디렉터리는 주소 탐색과 지도 표시를 위한 Next.js 앱입니다. Python 패키지 코드와 분리되어 있으며, React 클라이언트 상태로 주소 검색 결과를 탐색하고 Kakao 지도 위에 좌표·경계·반경 정보를 표시합니다.

## 실행

WSL 기준 실행 경로는 `/mnt/f/dev/python-kraddr-geo/web`입니다.

```bash
npm install
npm run dev
```

기본 주소는 `http://localhost:3010`입니다. 백엔드는 `http://localhost:3011`에서 실행합니다.
운영 빌드를 확인할 때는 다음 명령을 사용합니다.

```bash
npm run build
npm run start
```

## Kakao 지도 키

Kakao 지도 컴포넌트는 `react-kakao-maps-sdk`를 사용합니다. 실제 Kakao 지도를 표시하려면 `.env.local`에 JavaScript 키를 넣습니다.

```bash
NEXT_PUBLIC_KAKAO_JAVASCRIPT_KEY=카카오_자바스크립트_키
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3011
```

Kakao 개발자 콘솔의 JavaScript SDK 도메인은 실제 접속 주소와 일치해야 합니다.
현재 로컬 기본 주소는 `http://localhost:3010`입니다. `http://127.0.0.1:3010`으로
접속하려면 해당 주소도 Kakao JavaScript SDK 도메인에 추가해야 합니다.

키가 없거나 SDK 로딩에 실패하면 검색 UI와 정적 GIS 미리보기 화면이 유지됩니다.

## 주소 전체 목록

`전체 목록` 탭은 `backend/`의 FastAPI 서버에서 PostGIS 주소 목록을 받아옵니다. 로컬 샘플 4건이 아니라 `address_serving_juso_road_address` 테이블을 페이지 단위로 브라우징합니다.

목록 조회 흐름은 다음과 같습니다.

- 검색어는 도로명, 지번, 법정동코드, 도로명코드, PNU 성격의 값을 입력합니다.
- 검색 범위는 `전체`, `도로명`, `지번`, `코드` 중에서 선택합니다.
- 페이지당 표시 개수는 `5`, `10`, `20`, `50`, `100`개 중에서 선택합니다.
- 기본값은 `10`개입니다.
- 선택한 표시 개수는 `kraddr_geo_page_size` 쿠키에 저장되어 새로고침 후에도 유지됩니다.
- 조회 중에는 결과 목록 제목 옆에 회전 아이콘과 `처리 중` 배지가 표시됩니다.
- 새로고침 버튼은 현재 검색 조건과 페이지 번호를 유지한 채 다시 조회합니다.

## 주요 파일

- `src/app/page.tsx`: 주소 탐색 화면 진입점
- `src/components/address-explorer.tsx`: 검색, 필터, 결과 목록, 코드 상세 패널
- `src/components/kakao-map-panel.tsx`: Kakao 지도와 정적 GIS 미리보기
- `src/data/address-data.ts`: 화면 검증용 주소 샘플과 코드 분해 함수

## 확인 명령

```bash
npm run lint
npm run build
```
