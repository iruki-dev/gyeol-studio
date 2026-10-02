# 브라우저 종단 테스트 (Playwright)

실제 Chromium에서 앱을 처음부터 끝까지 써 보고 화면을 캡처합니다. 마이크 자리에는 **가상 가수**(`singer.js`)가 들어갑니다.
가상 가수는 실제 사람이 부른 녹음 파일을, 앱의 녹음기(AudioWorklet)가 시작하는 프레임에 맞춰 마이크 스트림으로 흘려 넣습니다.
마이크 뒤의 모든 것 — 녹음기, 지연 보정과 자르기, 업로드, 분석, 코칭 — 은 실제 앱 코드입니다.

## 준비

```bash
cd tests/e2e && npm install                         # playwright
# 실제 노래: CSD(Children's Song Dataset, CC BY-NC-SA 4.0, https://zenodo.org/records/4916302)에서
# korean/wav/kr003a.wav 와 korean/csv/kr003a.csv(곰 세마리)를 받아 <CSD>/korean/ 아래에 두고:
python tests/e2e/make_material.py <CSD>/korean <AUDIO>
```

`make_material.py`는 다음을 만듭니다(저장소에는 넣지 않음).

| 파일 | 내용 |
|---|---|
| `gom3_song.wav` | 노래 앞 24초 + 음표 기록으로 만든 반주(베이스·화음·하이햇) → 앱에 올리는 곡 |
| `gom3_take_v2.wav` | 같은 가사를 2절에서 다시 부른 부분 → **같은 가수의 두 번째 실제 연주** |
| `gom3_take_flat.wav` | 위 녹음을 35센트 낮춘 것(음 높이만 바꿈) |
| `gom3_phrase.txt` | 곡에서 소절 구간(초) |

4·5단계(기술 녹음·학습·안내 투어)는 여러 가수가 같은 가락을 여러 방식으로 부른 실제 녹음이 필요해서
[VocalSet](https://zenodo.org/records/1442513)(CC BY 4.0)에서 필요한 파일만 받아 씁니다(전체 2.6GB 중 약 70MB, `pip install remotezip`).

```bash
python tests/e2e/make_technique_material.py <AUDIO>     # vs_*.wav + technique_plan.json
python tests/e2e/make_check_material.py <AUDIO>         # 3단계 시작 검사용 합성 음
```

## 실행

```bash
python -m gyeol_studio --console --no-browser --data-dir /tmp/gs-e2e     # 빈 데이터 폴더로
BASE=http://127.0.0.1:8765 AUDIO=<AUDIO> SHOTS=docs/screenshots/phase-1 node tests/e2e/phase1.mjs
```

`phase4.mjs`는 테스터 6명의 기술 녹음 짝(첫 짝은 브라우저의 기술 녹음 모드로)과 학습 시작·멈춤·이어서·비교·적용·되돌리기를,
`phase5.mjs`는 새 사용자의 안내 투어, 휴대폰(아이폰 브라우저 흉내) 접속, 오류 문구를 확인합니다.
단계별 스크립트(`phase1.mjs` …)가 화면을 눌러 가며 진행하고, `shots.mjs`는 이미 있는 데이터로 화면만 캡처합니다.
