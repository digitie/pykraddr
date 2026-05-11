# pykraddr 웹 UI

`web` 디렉터리는 주소 탐색과 지도 표시를 위한 Next.js 앱입니다. Python 패키지 코드와 분리되어 있으며, React 클라이언트 상태로 주소 검색 결과를 탐색하고 Kakao 지도 위에 좌표·경계·반경 정보를 표시합니다.

## 실행

```bash
npm install
npm run dev
```

기본 주소는 `http://localhost:3010`입니다. 백엔드는 `http://localhost:3011`에서 실행합니다.

## Kakao 지도 키

Kakao 지도 컴포넌트는 `react-kakao-maps-sdk`를 사용합니다. 실제 Kakao 지도를 표시하려면 `.env.local`에 JavaScript 키를 넣습니다.

```bash
NEXT_PUBLIC_KAKAO_JAVASCRIPT_KEY=카카오_자바스크립트_키
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3011
```

키가 없거나 로딩에 실패하면 검색 UI와 정적 GIS 미리보기 화면이 유지됩니다.

## 주소 전체 목록

`전체 목록` 탭은 `backend/`의 FastAPI 서버에서 PostGIS 주소 목록을 받아옵니다. 로컬 샘플 4건이 아니라 `address_serving_juso_road_address` 테이블을 페이지 단위로 브라우징합니다.

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
