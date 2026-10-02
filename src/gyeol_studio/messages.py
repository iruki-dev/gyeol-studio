"""Korean wording for failures: what went wrong and what to do, in one or two sentences.

gyeol reports reasons in English (``Result.reason``); ``korean_reason`` maps
the known ones to everyday Korean.  Unknown reasons get a general sentence and
the original text is kept for "자세히 보기".
"""

from __future__ import annotations

import re

# (pattern on the library's reason, Korean message)
_PATTERNS: list[tuple[str, str]] = [
    (r"shorter than 300 ms", "녹음이 너무 짧아요. 소절이 끝날 때까지 불러 주세요."),
    (r"silent|contains NaN", "소리가 거의 녹음되지 않았어요. 마이크가 연결되어 있는지, 브라우저에 마이크 권한을 줬는지 확인해 주세요."),
    (r"no voiced frames|pitch analysis failed|too few voiced", "노래하는 목소리를 찾지 못했어요. 마이크 가까이에서 조금 더 크게 불러 주세요."),
    (r"cannot read audio|Error opening|Format not recognised|unsupported|could not decode",
     "이 음원 파일을 읽을 수 없어요. MP3, WAV, FLAC, OGG 파일로 바꿔서 다시 올려 주세요."),
    (r"no fetched weights|run `gyeol fetch", "보컬 분리 모델이 아직 준비되지 않았어요. 설정 → 모델에서 '받기'를 눌러 주세요."),
    (r"checksum mismatch", "받은 모델 파일이 손상됐어요. 인터넷 연결을 확인하고 다시 받아 주세요."),
    (r"URLError|getaddrinfo|Name or service not known|timed out|Connection (reset|refused)|HTTP Error",
     "인터넷에 연결할 수 없어서 받지 못했어요. 연결을 확인한 뒤 다시 시도해 주세요."),
    (r"No space left|disk full|Errno 28", "저장 공간이 부족해요. 디스크 공간을 비우거나 설정에서 데이터 폴더를 다른 곳으로 옮겨 주세요."),
    (r"Permission denied|Errno 13", "데이터 폴더에 저장할 권한이 없어요. 설정에서 다른 데이터 폴더를 골라 주세요."),
    (r"MemoryError|out of memory|Unable to allocate", "메모리가 부족해요. 다른 프로그램을 닫고 다시 시도하거나, 더 짧은 곡으로 해 보세요."),
    (r"no confident item", "시범음을 만들 만큼 확실한 차이가 없어요."),
    (r"separation (required|failed)", "보컬과 반주를 나누지 못했어요. 다른 음원 파일로 다시 시도해 주세요."),
    (r"no register / phonation / laryngeal labels|carries no", "학습에 쓸 라벨이 아직 없어요. 데이터 화면에서 녹음에 발성·음질 라벨을 붙여 주세요."),
    (r"not enough singers|too few singers|split", "학습하려면 여러 사람의 녹음이 필요해요. 최소 3명 이상의 녹음과 라벨을 모아 주세요."),
]


def korean_reason(reason: str) -> str:
    for pat, msg in _PATTERNS:
        if re.search(pat, reason or "", re.IGNORECASE):
            return msg
    return "처리하는 중에 문제가 생겼어요. 다시 시도해 보고, 계속되면 '자세히 보기' 내용을 개발팀에 알려 주세요."


# Messages for the API (HTTP errors).  Codes are stable; the UI shows `message`.
API = {
    "no_user": "먼저 사용자를 선택하거나 등록해 주세요.",
    "user_exists": "같은 이름의 사용자가 이미 있어요. 다른 이름을 써 주세요.",
    "name_required": "이름을 입력해 주세요.",
    "consent_required": "분석에 동의해야 녹음과 피드백을 쓸 수 있어요.",
    "not_found": "찾는 항목이 없어요. 이미 지워졌을 수 있어요. 목록으로 돌아가 다시 골라 주세요.",
    "file_required": "음원 파일을 골라 주세요.",
    "bad_audio": "이 음원 파일을 읽을 수 없어요. MP3, WAV, FLAC, OGG 파일로 바꿔서 다시 올려 주세요.",
    "too_long": "곡이 너무 길어요(15분 이하만 올릴 수 있어요). 필요한 부분만 잘라서 올려 주세요.",
    "title_required": "곡 제목을 입력해 주세요.",
    "bad_range": "소절 구간이 올바르지 않아요. 시작이 끝보다 앞에 오도록, 0.5초~30초 길이로 지정해 주세요.",
    "song_not_ready": "아직 보컬 분리가 끝나지 않았어요. 곡 보관함에서 진행 상황을 확인해 주세요.",
    "phrase_not_ready": "목표 분석이 아직 끝나지 않았어요. 잠시 후 다시 시도해 주세요.",
    "bad_recording": "녹음 파일이 올바르지 않아요. 다시 녹음해 주세요.",
    "recording_too_short": "녹음이 너무 짧아요. 소절이 끝날 때까지 불러 주세요.",
    "feedback_not_ready": "아직 분석 중이에요. 잠시만 기다려 주세요.",
    "bad_response": "응답을 다시 골라 주세요.",
    "bad_settings": "설정 값이 올바르지 않아요. 다시 확인해 주세요.",
    "data_dir_unusable": "그 폴더에는 저장할 수 없어요. 다른 폴더를 골라 주세요.",
    "job_not_cancellable": "이 작업은 지금 멈출 수 없어요. 끝날 때까지 기다려 주세요.",
    "no_training_data": "학습에 쓸 수 있는 녹음이 없어요. 학습 동의를 받은 녹음에 라벨을 붙여 주세요.",
    "training_running": "이미 학습이 진행 중이에요. 끝나거나 멈춘 뒤에 새로 시작해 주세요.",
    "local_only": "이 기능은 앱을 실행한 PC에서만 쓸 수 있어요.",
}
