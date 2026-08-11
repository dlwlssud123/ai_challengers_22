# 폭염 정책 나침반 - 실행 및 연동 가이드

지자체 담당자가 행정동별 폭염 취약도와 대응시설 사각지대를 확인하고, 예산 안에서 신규 시설 후보와 정책 우선순위를 검토하는 Streamlit MVP입니다. 기획서의 핵심 흐름인 취약도/시설 현황 → 입지 추천 → Before/After → LLM 설명을 한 화면으로 통합했습니다.

## 실행

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

`pip`와 `streamlit` 명령만 직접 실행하면 서로 다른 Python 환경을 가리킬 수 있습니다. 반드시 같은 환경의 `python -m pip`와 `python -m streamlit`을 사용하세요.

왼쪽 패널에서 지역, 예산, 시설 수를 선택하고 `정책 분석 실행`을 누릅니다. 기본 Mock 모드는 API 키와 모델 파일 없이 동작합니다. 테스트는 `pytest -q`로 실행합니다.

## 파일 구성

- `app.py`: Streamlit 통합 화면
- `src/integration.py`: `run_policy_analysis(region, budget, max_facilities, use_mock)`
- `src/vulnerability.py`, `src/accessibility.py`, `src/optimization.py`: 팀 모델 어댑터
- `src/alan_client.py`: 프롬프트, 응답 검증, API 전송 경계
- `src/mock_data.py`: 시연 데이터와 예산 기반 휴리스틱
- `tests/test_integration.py`: 통합·안전 조건 테스트

## Alan API 설정

`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사하고 `ALAN_API_KEY`, `ALAN_API_URL`을 채우거나 같은 이름의 환경변수를 사용합니다. 실제 Alan API 공식 요청 필드가 제공되지 않았으므로 엔드포인트나 파라미터를 추측하지 않았습니다. `src/alan_client.py`의 `_build_request_payload()`만 공식 명세에 맞게 구현하면 HTTP timeout/오류/JSON 파싱과 응답 검증 경계를 사용할 수 있습니다. 연결 전까지는 Mock 정책을 반환합니다.

## 모델 담당자 연동 계약

- 취약도: `provider(region: str) -> dict`
- 접근성: `provider(region: str) -> dict`
- 최적화: `provider(region, budget, max_facilities, vulnerability, accessibility) -> dict`

각 반환값은 기획 요구사항의 필드명을 사용해야 합니다. 실제 provider를 통합 코드에 연결하기 전에는 실데이터 모드도 개별 오류를 경고로 기록하고 Mock 결과로 대체합니다.

## TODO와 한계

- SGIS 2025 행정동 경계 API가 연결되어 대구 150개 행정동의 실제 경계를 표시합니다. API 장애 시에만 간이 Mock 경계로 대체합니다.
- 취약도 색상과 상세 분석값은 아직 3개 행정동의 Mock 데이터이며 공공데이터·학습 모델 연결이 필요합니다.
- 입지 선택은 보호인구/비용 비율 휴리스틱이며 담당자의 최적화 모델로 교체할 수 있습니다.
- Alan 공식 명세 확인 후 요청 payload와 실제 응답 콘텐츠 추출 규칙을 구현해야 합니다.
- Mock 수치와 기대효과는 집행 근거가 아니며 최신 데이터와 현장 검증이 필요합니다.
