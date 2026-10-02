# gyeol 라이브러리 요청 사항

앱을 만들면서 라이브러리(`iruki-dev/gyeol`)에 필요하다고 판단한 기능과 발견한 문제입니다. 앱 안에서 우회하지 않고, 앱이 지금 어떻게 동작하는지와 함께 적었습니다. 확인한 라이브러리 버전은 `gyeol 2.0.0.dev0`(2026-10-01 main)입니다.

| # | 분류 | 제목 | 앱에 미치는 영향 | 우선순위 |
|---|---|---|---|---|
| 1 | 기능 | 소절 단위 목표 분리(`TargetSeparation` 구간 자르기) | 소절 녹음에서 반주 새어 듦(bleed) 감지를 못 씀 | 높음 |
| 2 | 기능 | `separate_target` 진행률·취소 | 보컬 분리 진행률을 시간으로 추정해서 보여 줌 | 중간 |
| 3 | 기능 | `fetch`의 Python API와 진행률, 파일 크기 | 받은 크기를 `.part` 파일로 재서 보여 줌 | 중간 |
| 4 | 버그 | 표시 기준 맞추기(knob recovery)가 받은 모델에 따라 결과가 달라짐 | 빌드 스크립트에서 캐시 폴더를 비워서 맞춤 | 높음 |
| 5 | 기능 | 기본 표시 기준(ThresholdSet) 제공과 항목 범위 | 강약·빠르기·꾸밈음 대부분이 기본 화면에 안 나옴 | 높음 |
| 6 | 기능 | 학습한 모델을 `api.analyze`에 적용 | 학습 화면의 "적용"이 분석 결과를 바꾸지 못함 | 높음 |
| 7 | 기능 | 녹음 하나에 음질 라벨 여러 개 | 음질을 둘 이상 고른 녹음은 학습용 `phonation`에서 빠짐 | 중간 |
| 8 | 품질 | 가사 음절 정렬(음표 수 비례 → 발음 시작 기반) | 근거 그래프의 음절 위치가 실제와 어긋날 때가 있음 | 중간 |
| 9 | 기능 | `api.train`의 중단 요청·구조화된 진행 정보 | 로그 줄을 읽어 진행률을 만들고, SIGINT로 멈춤 | 중간 |
| 10 | 기능 | 가중치 캐시 폴더 지정(`GYEOL_CACHE`) | 모델 파일이 앱 데이터 폴더가 아닌 `~/.cache/gyeol`에 저장됨 | 낮음 |

---

## 1. 소절 단위 목표 분리

**상황.** 앱은 곡 전체를 한 번 `api.separate_target`으로 나누고, 사용자는 그중 한 소절(보통 3–15초)만 따라 부릅니다. `api.analyze(take, target=ts)`는 곡 전체의 `TargetSeparation`을 받아 `detect_bleed(x, ts.accompaniment, sr)`로 반주 새어 듦을 판단하는데, 녹음은 소절 길이이고 반주는 곡 길이라 시간축이 맞지 않습니다. `analyze(separated=ts)`도 `PrecomputedSeparator`가 길이가 다르면 거절합니다("cached separation does not belong to this recording").

**앱의 현재 동작.**
- 목표: 분리된 보컬에서 소절 구간을 잘라 `api.analyze(vocal_slice, sr, separation="off", lyrics=…)`.
- 녹음: 이어폰으로 들었으면 `separation="off"`, 스피커로 반주를 틀었으면 같은 구간의 반주를 `backing=`으로 넘김(항상 빼기).
- 그래서 이어폰 녹음의 약한 새어 듦은 감지하지 못합니다.

**요청.** `TargetSeparation.segment(start_s, end_s)`(같은 키 + 구간 정보) 또는 `api.analyze(take, target=ts, segment=(start_s, end_s))`. 그러면 소절 녹음에도 리비전 D1의 "새어 들 때만 분리" 정책을 그대로 쓸 수 있습니다.

## 2. `separate_target` 진행률·취소

**상황.** BS-RoFormer 분리는 이 앱의 테스트 PC(4코어 CPU)에서 곡 길이의 약 7–8배 걸립니다(24초 곡 → 약 3분, 4분 곡이면 30분 안팎). 라이브러리는 8초 단위 조각으로 처리하지만 진행 상황을 밖으로 알려 주지 않습니다.

**앱의 현재 동작.** 지난 분리에서 잰 속도(스레드당 실시간 배율)로 예상 시간을 계산해 진행 막대를 움직입니다. 예상보다 길어지면 "예상보다 조금 더 걸리고 있어요"라고 씁니다. 취소하면 작업 프로세스를 통째로 다시 시작합니다.

**요청.** `separate_target(..., progress=callable(done_chunks, total_chunks))`와 협조적 취소(`should_stop=callable`). `SeparationQueue`의 Future에도 같은 정보가 있으면 좋겠습니다.

## 3. `fetch`의 Python API와 진행률

**상황.** 첫 실행 때 앱이 `gyeol fetch bs_roformer_viperx_ep317`(약 640MB)을 대신 실행합니다. `gyeol.cli._fetch`는 `urllib.request.urlretrieve`로 받고 진행률을 내보내지 않으며, Python에서 부를 공개 함수가 없습니다. `Asset`에는 파일 크기가 없습니다(설명 문구에만 있음).

**앱의 현재 동작.** `gyeol.cli.main(["fetch", name])`을 스레드에서 실행하고, `<파일>.part` 크기를 0.5초마다 읽어 진행률과 남은 시간을 만듭니다. 전체 크기는 HTTP `Content-Length`, 없으면 앱에 적어 둔 639,331,213 바이트를 씁니다. 중간에 끊기면 처음부터 다시 받습니다.

**요청.** `gyeol.api.fetch(name, dest=None, progress=callable(bytes, total)) -> Result[Path]`, `Asset.size` 필드, 이어받기(HTTP Range).

## 4. 버그: 표시 기준 맞추기 결과가 받은 모델에 따라 달라짐

**재현.** `python examples/fit_thresholds.py --synthetic`을 BS-RoFormer 가중치를 받기 전과 후에 각각 실행합니다.

| | 받기 전 (22초) | 받은 뒤 (5분 이상) |
|---|---|---|
| intonation_offset MDC95 | 0.75 센트 | 1.72 센트 |
| onset_timing MDC95 | 13.94 ms | 24.29 ms |
| vibrato_extent MDC95 | 28.71 센트 | 54.01 센트 |
| contour_deviation | 사용 가능 | **목록에서 빠짐** |

**원인.** `gyeol.eval.knob_recovery.knob_recovery`가 `analyze(Recording(x, sr), trackers=…)`를 기본 `separation="auto"`로 부르고, 이를 바꿀 인자가 없습니다. 가중치가 캐시에 있으면 합성 녹음(분홍 잡음 조건 포함)을 BS-RoFormer로 분리해서 측정값이 바뀝니다.

**앱의 현재 동작.** `scripts/make_thresholds.py`가 홈 폴더를 빈 임시 폴더로 바꿔 가중치가 안 보이게 한 뒤 맞춥니다(받기 전과 같은 결과).

**요청.** `knob_recovery(..., separation="off")` 인자(합성 녹음에는 기본값을 `"off"`로 해도 됨).

## 5. 기본 표시 기준 제공과 항목 범위

**상황.** `gyeol.coach.thresholds`는 "맞춘 기준이 없는 항목은 보여 주지 않는다"는 정책이고 라이브러리에는 맞춘 기준 파일이 없습니다. 예제(합성 knob recovery)로 맞출 수 있는 항목은 `intonation_offset`, `onset_timing`, `vibrato_extent`, `contour_deviation`뿐이고 `global_offset`은 "신뢰할 수 없음"으로 나옵니다.

**영향(실제 확인).** 실제 노래(CSD 동요) 녹음 첫 번째에서 `compare`가 낸 항목 58개 중 21개는 기준이 아예 없어서(`no_threshold`) 빠졌습니다(두 번째 녹음은 57개 중 23개). 1단계 목표인 **강약(`loudness`, `dynamic_range`)은 기준이 없어 기본 화면에 나오지 않습니다**. `tempo`, `interval_compression`, `transition_deviation`, `scoop`, `fall`, `vibrato_rate`, `breathiness`도 마찬가지입니다. 또 노래 전체를 35센트 낮게 부른 녹음에서 `global_offset`(−37센트, 신뢰도 0.85)은 기준이 "신뢰할 수 없음"이라 빠지고, 음마다의 `intonation_offset`만 남습니다.

**앱의 현재 동작.** 라이브러리 예제와 같은 방법으로 만든 합성 기준(`resources/thresholds.json`, provenance `synthetic: true`)을 앱에 넣고, 화면에 "합성 데이터로 정한 임시 기준"이라고 알립니다. 설정 → 고급의 "검증 기준이 없는 항목도 보기(실험)"를 켜면 기준 없는 항목을 '참고용' 표시와 함께 뒤에 보여 줍니다(기본은 꺼짐).

**요청.**
- 강약·빠르기·꾸밈음·음 이동에 대한 knob recovery(합성 정답이 있는 항목부터).
- `global_offset`을 신뢰할 수 있게 만들 재검사 조건(현재 재검사 쌍 8개).
- 검증 데이터로 맞춘 기본 `ThresholdSet` 파일과 이를 읽는 공개 함수(예: `gyeol.coach.default_thresholds()`).
- 앱은 "맞아요 / 아닌 것 같아요 / 모르겠어요" 응답과 박자 라벨을 모으고 있으니, 이 데이터로 기준을 맞추는 도구도 있으면 좋겠습니다.

## 6. 학습한 모델을 `api.analyze`에 적용

**상황.** `api.train`으로 `heads`를 학습하면 체크포인트(`best.pt`, 보정 포함)가 나오지만, `api.analyze`에는 이를 넘길 인자가 없습니다. 내부의 `AnalysisConfig.heads`는 공개 API 밖입니다.

**앱의 현재 동작.** 학습 화면에서 새 모델과 현재 모델의 평가 점수를 나란히 보여 주고 "적용/되돌리기"로 사용할 모델을 기록하지만, **분석에는 아직 반영되지 않는다고 화면에 알립니다.**

**요청.** `api.analyze(..., heads="path/to/best.pt")` 또는 `api.load_model(checkpoint)`처럼 공개 API로 학습된 heads를 쓰는 방법.

## 7. 녹음 하나에 음질 라벨 여러 개

**상황.** `gyeol.train.tasks.head_targets`는 `labels["phonation"]`을 문자열 하나로 읽습니다. 사람이 들으면 "숨섞임 + 트왱"처럼 둘 이상이 함께 들리는 경우가 흔합니다.

**앱의 현재 동작.** 앱은 여러 개를 고를 수 있게 저장하고, 내보낼 때는 하나만 골랐으면 `phonation`, "해당 없음"이면 `phonation: null`(모든 음질 음성 예제), 둘 이상이면 `phonation`을 빼고 `qualities: [...]`로 따로 적습니다(학습에는 안 쓰임).

**요청.** `phonation: ["breathy", "pharyngeal_twang"]` 같은 다중 라벨 지원(시그모이드 헤드라 구조상 가능해 보임).

## 8. 가사 음절 정렬

**상황.** `assign_syllables`는 음표 수와 음절 수가 다를 때 음표 길이에 비례해서 음절을 나눕니다. 실제 동요 녹음("곰 세마리가 한 집에 있어 아빠곰 엄마곰 애기곰", 19음절)에서 음표가 17개로 잡혀 "세마", "곰엄", "기곰"처럼 묶였고, "엄마곰"의 "엄"이 앞 음표의 "곰"과 합쳐졌습니다.

**앱의 현재 동작.** 라이브러리가 준 음절을 그대로 근거 그래프와 녹음 중 가사 표시에 씁니다.

**요청.** 자음 시작(onset)과 모음 구간을 이용한 정렬, 또는 정렬 신뢰도를 함께 돌려주기(낮으면 앱이 음절 대신 "1번째 음"처럼 표시할 수 있게).

## 9. `api.train`의 중단 요청과 진행 정보

**상황.** 학습 중단은 메인 스레드의 SIGINT/SIGTERM 처리기로만 됩니다. 진행 정보는 `log` 콜백의 문자열(`[train] step 10/40 … ETA 0:00:12`, `[val] step …`)과 CSV 파일뿐입니다.

**앱의 현재 동작.** 학습을 작업 프로세스의 메인 스레드에서 돌리고, 사용자가 "멈추기"를 누르면 감시 스레드가 `signal.raise_signal(SIGINT)`을 보냅니다(Windows에서도 같은 프로세스 안이라 동작). 진행률·남은 시간·검증 점수는 로그 줄을 정규식으로 읽습니다.

**요청.** `api.train(..., should_stop=callable, on_progress=callable(dict))` — `{"step", "total_steps", "eta_s", "phase": "prepare|train|validate", "val": {...}}`.

## 10. 가중치 캐시 폴더 지정

`gyeol.cli.CACHE`가 `~/.cache/gyeol`로 고정이라 모델 파일이 앱의 데이터 폴더 밖에 저장됩니다. 데이터 폴더를 외장 디스크로 옮겨도 640MB 모델은 시스템 디스크에 남습니다. `GYEOL_CACHE` 환경 변수나 `fetch(dest=…)`와 짝을 이루는 로더 인자가 있으면 좋겠습니다.
