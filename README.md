# 결 스튜디오 (gyeol-studio)

[gyeol](https://github.com/iruki-dev/gyeol) 라이브러리로 만든 보컬 코칭 앱입니다. 목표 곡의 한 소절을 따라 부르면, 무엇이 다른지(음정·박자·강약 등) 알려 주고 내 목소리로 만든 시범음을 들려줍니다. 녹음과 피드백 응답, 라벨은 이 PC에 쌓여 모델 학습 데이터가 됩니다.

- **쓰는 사람**: 비개발자 팀원과 테스터. 설치부터 사용까지 터미널이 필요 없습니다 → [설치 안내](docs/설치-안내.md)
- **구성**: PC에서 도는 서버(Python, FastAPI) + 브라우저 화면(PC와 휴대폰). 분석은 `gyeol.api`만 씁니다.
- **데이터**: 모든 데이터는 PC의 데이터 폴더 하나(기본 `문서/gyeol-studio`)에 저장됩니다. 설정에서 바꿀 수 있어요.

## 화면

| 곡 보관함 | 소절 만들기 | 코칭 | 휴대폰 |
|---|---|---|---|
| ![](docs/screenshots/phase-1/08-library-progress.png) | ![](docs/screenshots/phase-1/06-phrase-select.png) | ![](docs/screenshots/phase-1/16-feedback.png) | ![](docs/screenshots/phase-1/21-mobile-feedback.png) |

## 진행 기록

| 단계 | 내용 | 문서 |
|---|---|---|
| 1 | 실행 파일, 곡 보관함, 소절, 녹음, 코칭(음정·박자·강약) | [docs/phase-1.md](docs/phase-1.md) |
| 2 | 피드백 응답, 라벨, 녹음 조건, 내보내기 | [docs/phase-2.md](docs/phase-2.md) |
| 3 | 시작 검사, 연습 기록, 사용자 프로필 | [docs/phase-3.md](docs/phase-3.md) |
| 4 | 기술 녹음 모드, 학습 관리 | [docs/phase-4.md](docs/phase-4.md) |
| 5 | 휴대폰 접속(QR·HTTPS), 안내 투어, 오류 문구 | [docs/phase-5.md](docs/phase-5.md) |

라이브러리에 필요한 기능과 발견한 문제: [docs/library-requests.md](docs/library-requests.md)

## 개발자용

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
python -m gyeol_studio                                  # 서버 + 브라우저 (끝내기: 창 닫기 / Ctrl+C)
python -m gyeol_studio --console --no-browser --data-dir ./test-data   # 터미널에서, 별도 데이터 폴더로
pytest                                                  # API 흐름 테스트 (작업 프로세스 포함)
```

브라우저 종단 테스트(Playwright, 가상 가수 마이크): [tests/e2e/README.md](tests/e2e/README.md)

실행 파일 만들기: GitHub Actions의 `build` 워크플로를 수동 실행(또는 `v*` 태그)하면 Windows(`gyeol-studio-windows.zip`)와 macOS(`gyeol-studio-macos-*.zip`) 앱이 만들어집니다. 로컬에서는 `pip install -e ".[build]" pillow && python scripts/make_icons.py && pyinstaller packaging/gyeol-studio.spec`.

### 구조

```
src/gyeol_studio/
  launcher.py      더블클릭 진입점: 서버(http + 휴대폰용 https) 시작, 브라우저 열기, 작은 상태 창
  server.py        FastAPI 앱, 작업 프로세스 관리(죽으면 다시 시작, 멈출 수 없는 작업 취소)
  worker.py        작업 프로세스: fast(분석·코칭) / slow(모델 받기·보컬 분리) / train(학습)
  jobs.py          SQLite에 저장되는 작업 큐 — 앱을 닫았다 열어도 이어서 진행
  db.py            SQLite 스키마(사용자, 곡, 소절, 녹음, 분석, 피드백, 라벨, 검사, 학습, 작업)
  tasks/           작업 처리기 (gyeol.api 호출은 모두 여기)
  coaching.py      gyeol.coach로 거르고 정렬 → 핵심 1개 + 부가 2개, 근거 그래프 데이터
  routes/          JSON API
  web/             브라우저 화면 (빌드 없는 ES 모듈)
  resources/       동의 문구 기본값, 코칭 문구, 표시 기준(thresholds.json)
scripts/           표시 기준 만들기, 아이콘 만들기
packaging/         PyInstaller 설정
tests/             pytest(API) + e2e(Playwright)
docs/              단계별 기록, 화면 캡처, 라이브러리 요청
```

## 라이선스

MIT. 보컬 분리 모델(BS-RoFormer viperx ep317)은 앱에 들어 있지 않고 첫 실행 때 `gyeol fetch`로 받습니다. 원 출처에 라이선스가 적혀 있지 않습니다(gyeol의 자산 목록 참고). 테스트에 쓴 노래(CSD, VocalSet)는 저장소에 넣지 않았습니다.
