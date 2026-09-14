<p align="center">
  <img src="./docs/assets/artemis-banner.png?v=7" alt="ARTEMIS Banner" width="100%" />
</p>

<p align="center">
  <strong>AI 어시스턴트와 테스트 스위트가 사람처럼 실제 휴대폰을 다루게 합니다.</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> •
  <a href="./README_CN.md">中文文档</a> •
  <a href="./README_KR.md"><b>한국어</b></a> •
  <a href="#workflow-showcase">워크플로 시연</a> •
  <a href="#quick-start">빠른 시작</a> •
  <a href="#mcp-setup">IDE용 MCP</a> •
  <a href="#benchmarks">벤치마크</a> •
  <a href="https://discord.gg/wF2FN4WHGY">Discord 커뮤니티</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-Native%20Server-8A2BE2.svg" alt="MCP Native"></a>
  <a href="https://ai.google.dev/"><img src="https://img.shields.io/badge/Multimodal-Gemini%20%7C%20Claude%20%7C%20GPT--4o%20%7C%20Qwen--VL-4285F4.svg" alt="Multi-Model"></a>
  <a href="https://github.com/google-research/android_world"><img src="https://img.shields.io/badge/AndroidWorld-99%25%2B%20SOTA-success.svg" alt="AndroidWorld SOTA"></a>
</p>

<!-- Demo Showcase -->
<p align="center">
  <img src="./docs/assets/demo.gif" alt="Artemis in Action" width="100%" />
  <br>
  <em>실기기 시연: Google Maps에서 주행 경로를 설정하고 총 소요 시간을 계산한 뒤, YouTube를 열어 Coldplay 곡을 재생합니다.</em>
</p>

## 핵심 특징

* **앱 간 자동화**: 자연어 지시만으로 Android에서 테스트 워크플로와 일상적인 작업을 수행합니다.
* **멀티모달 타게팅**: 엘리먼트 인덱스를 우선 사용하고, 커스텀 인터페이스에는 좌표와 시각 기반 위치 탐색을 폴백으로 제공합니다.
* **IDE 내 진단**: **Model Context Protocol (MCP)** 연동으로 **Antigravity, Claude Code, Windsurf**가 테스트 기기를 직접 조작하고 **Logcat** 출력과 스크린샷을 수집합니다.
* **Flash 실행**: 관측-실행 반응 루프와 비동기 히스토리 요약으로 스텝당 통상 **3~5초**.
* **Pro 탐색**: 개별 액션 실행 전 대상을 검증하고, 차단된 액션은 Operator에게 되돌려 복구하게 합니다. 장시간 탐색 테스트와 안정성 테스트를 지원합니다.
* **AndroidWorld 결과**: Google Research의 **AndroidWorld** 벤치마크(100개 이상의 멀티스텝 태스크)에서 **99%+ 태스크 완료율**.

<a id="workflow-showcase"></a>
## Antigravity × ARTEMIS: 자율 테스트 워크플로

**Antigravity**는 MCP를 통해 **ARTEMIS**를 사용하여, 테스트 요청 하나를 계획·기기 실행·진단 리포트로 이어 갑니다:

<table width="100%">
  <tr>
    <td width="50%" align="center">
      <b>1. 프롬프트 입력 (태스크 발행)</b><br>
      <sub>Antigravity에서 테스트 시나리오와 측정 지표를 서술</sub><br><br>
      <img src="./docs/assets/workflow-1-prompt.png" width="100%" alt="Step 1: Prompt Input in Antigravity" />
    </td>
    <td width="50%" align="center">
      <b>2. 테스트 계획 생성</b><br>
      <sub>검토할 수 있는 단계별 테스트 계획과 구조를 수립</sub><br><br>
      <img src="./docs/assets/workflow-2-plan.png" width="100%" alt="Step 2: Test Plan Generation" />
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <b>3. 자율 테스트 실행</b><br>
      <sub>실기기를 구동해 UI를 탐색하고 성능을 프로파일링</sub><br><br>
      <img src="./docs/assets/workflow-3-exec.png" width="100%" alt="Step 3: Autonomous Test Execution" />
    </td>
    <td width="50%" align="center">
      <b>4. 최종 리포트</b><br>
      <sub>구조화된 감사 결과, 지표 표, 원본 데이터셋을 산출</sub><br><br>
      <img src="./docs/assets/workflow-4-report.png" width="100%" alt="Step 4: Final Report" />
    </td>
  </tr>
</table>

<a id="quick-start"></a>
## 빠른 시작

**USB 디버깅**이 켜진 Android 기기 또는 에뮬레이터가 연결되어 있는지 확인하세요. 원클릭 시작 스크립트가 다음을 자동으로 처리합니다:
- **시스템 툴체인 설치**: ADB, scrcpy, FFmpeg, Python(`uv`) 의존성을 감지하고 자동 설치합니다.
- **전역 MCP 서버 및 AI 에이전트 규칙 등록**: 사용 중인 AI IDE(**Antigravity**, **Cursor**, **Claude Code**, **Codex**, **Windsurf**, **VS Code**, **Cline/Roo**, **OpenClaw**)에 전역 MCP 설정과 **Artemis 모바일 테스트 마인드셋(`rules.md`)**을 자동 설치할지 물어봅니다.

### macOS 및 Linux

```bash
# 1. 저장소 클론 후 디렉터리 이동
git clone https://github.com/google/artemis.git && cd artemis

# 2. 원클릭 실행
./start.sh
```

### Windows PowerShell

```powershell
# 1. 저장소 클론 후 디렉터리 이동
git clone https://github.com/google/artemis.git
cd artemis

# 2. 원클릭 실행
.\start.bat
```

> PowerShell은 기본적으로 현재 디렉터리에서 실행 스크립트를 찾지 않으므로, 끝에 `\` 없이 `.\start.bat`으로 실행하세요. 명령 프롬프트(CMD)에서는 `start.bat`을 사용합니다.

> **팁**: 기본 브라우저에서 `http://localhost:8000`이 열리며 기기 연결 마법사, 실시간 화면 미러링, 프롬프트 샌드박스, 실행 리플레이를 제공합니다. CLI에서 바로 실행할 수도 있습니다: `uv run artemis run "Open Settings, find Battery and tell me current level" --profile flash`.

<a id="mcp-setup"></a>
<a id="mcp"></a>
<details>
<summary><b>Codex / Antigravity / Claude Code / Windsurf MCP 설정 (클릭하여 펼치기)</b></summary>

<br>

ARTEMIS에는 네이티브 **Model Context Protocol (MCP)** 서버가 포함되어 있습니다. 실제 휴대폰을 AI IDE에 직접 연결하세요:

### 1. 원클릭 자동 설치 (권장)

`./start.sh`(macOS/Linux) 또는 `.\start.bat`(Windows PowerShell)을 실행하면 감지된 IDE에 전역 MCP와 테스트 규칙을 설정할지 물어봅니다. 아래 명령으로 언제든 직접 설치하거나 갱신할 수도 있습니다:

```bash
# Antigravity / Jetski에 MCP 서버 및 전역 규칙 자동 설치:
uv run artemis mcp --install antigravity

# 또는 지원되는 모든 AI IDE에 설치 (Codex 포함):
uv run artemis mcp --install all
```

> **팁**: `uv run artemis init`으로 최초 설정 과정에서 대화형으로 MCP를 구성할 수도 있습니다.
> **참고**: 어느 디렉터리에서든 `uv run` 없이 `artemis` 명령을 쓰고 싶다면, 프로젝트 루트에서 `uv tool install -e .`를 한 번 실행하세요.

### 2. 수동 설정 (선택)

직접 설정하려면 `uv run artemis mcp --generate-config <client>`(예: `codex`, `antigravity`)를 실행해 알맞은 TOML 또는 JSON 스니펫을 출력하세요. `/path/to/artemis`는 실제 저장소 경로로 바꾸고, `command`는 `.venv`의 Python 실행 파일을 가리키게 합니다:

* **Codex** (`~/.codex/config.toml`):
```toml
[mcp_servers.artemis]
command = "/path/to/artemis/.venv/bin/python"
args = ["-m", "mcp_server"]
cwd = "/path/to/artemis"

[mcp_servers.artemis.env]
PYTHONUNBUFFERED = "1"
PYTHONPATH = "/path/to/artemis"
```

* **Antigravity** (`~/.gemini/jetski/mcp_config.json`):
```json
{
  "mcpServers": {
    "artemis": {
      "command": "/path/to/artemis/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/artemis",
      "env": {
        "PYTHONUNBUFFERED": "1"
      },
      "tools": {
        "mobile_run_task": { "eager": true },
        "mobile_manage_task": { "eager": true },
        "mobile_get_device_state": { "eager": true },
        "mobile_inspect_trace": { "eager": true },
        "mobile_diagnose": { "eager": true }
      }
    }
  }
}
```

* **Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "artemis": {
      "command": "/path/to/artemis/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/artemis"
    }
  }
}
```

### 3. AI 에이전트용 행동 규칙 등록 (적극 권장)

AI 코딩 어시스턴트가 시니어 모바일 테스트 엔지니어의 엄밀함으로 동작하고 UI 상호작용을 지어내지 않도록, 전용 테스트 마인드셋 규칙 파일을 [`mcp_server/rules.md`](./mcp_server/rules.md)에 제공합니다 (**코드 작성 전 능동적 탐색**, **Flash 대 Pro 라우팅 전략**, **지연 시간 및 타이밍 보정**, **"동적 우선, 좌표 폴백" 위치 탐색 패턴**을 다룹니다).

[`mcp_server/rules.md`](./mcp_server/rules.md)를 사용 중인 AI IDE의 규칙 설정에 등록하거나 복사하세요:
* **Antigravity**: `rules.md` 내용을 워크스페이스 규칙, 전역 규칙 설정 또는 에이전트 지시문에 추가합니다.
* **Claude Code**: `artemis mcp --install claude`를 실행하면 규칙이 `~/.claude/rules/artemis.md`에 설치됩니다 (정확히 한 곳에만 설치하세요 — Claude Code는 `~/.claude/CLAUDE.md`와 `~/.claude/rules/*.md`를 모두 읽으므로, 중복 등록은 컨텍스트만 낭비합니다).
* **Cursor**: 내용을 `.cursorrules`에 복사하거나 `.cursor/rules/artemis.mdc`에 규칙 파일을 만듭니다.
* **Codex**: 내용을 `~/.codex/AGENTS.md`(또는 활성화된 `AGENTS.override.md`)에 추가합니다.
* **Windsurf / OpenClaw**: 워크스페이스 규칙 또는 전역 시스템 프롬프트에 추가합니다.

> 테스트 마인드셋과 MCP 구조에 대한 자세한 내용은 [MCP Server README](./mcp_server/README.md)를 참고하세요.

### 4. IDE 채팅에서 휴대폰에 지시하기
Codex, Antigravity, Claude Code에서 이렇게 지시하면 됩니다:
> *"최신 변경 사항을 APK로 빌드해서 연결된 기기에 설치하고, 테스트 계정으로 로그인 화면을 연 다음, 로그인 후 예상치 못한 팝업이 뜨는지 확인하고 마지막 화면의 스크린샷을 보여줘."*

</details>

<a id="cli-backend"></a>
<details>
<summary><b>API 키 없이 Claude Code / Codex CLI 구독으로 실행하기 (클릭하여 펼치기)</b></summary>

<br>

ARTEMIS는 모든 에이전트 노드를 로컬에 설치된 코딩 에이전트 CLI로 구동할 수 있습니다. 제공사 API 키 대신 **Claude Code 또는 Codex 구독**을 사용하므로 `GEMINI_API_KEY`도, `OCR_API_KEY`도, Google 계정도 필요하지 않습니다. CLI는 코딩 에이전트가 아니라 상태 없는 일회성 텍스트/비전 모델로 쓰이며 일반 provider처럼 꽂히므로, 폴백 체인·토큰 계측·트레이싱과 그 위의 LangGraph 노드는 그대로입니다.

```bash
# 1. CLI가 설치되어 있고 로그인되어 있는지 확인
claude          # 최초 1회 로그인    (또는: codex login)

# 2. 실행을 해당 백엔드로 지정
export ARTEMIS_LLM_CONFIG=config/llm-config.claude-cli.jsonc
export ARTEMIS_EXPLORER_VERSION=pro      # 필수 — 아래 설명 참고
uv run artemis run --profile flash "Open Settings and tell me the battery level"

# `artemis init`이 두 줄을 .env에 대신 써 주며, 데몬 워커도 여기서 값을 읽습니다.
# `uv run artemis doctor`로 확인하세요.
```

**`ARTEMIS_EXPLORER_VERSION=pro`만은 빠뜨리면 안 됩니다.** 포인트 그라운딩은 범용 모델로 이전되지 않는 유일한 능력입니다. Explorer의 `flash` 티어는 일회성 시각 탐지 — 모델에게 정규화된 `[x, y]`를 물어보고 그 지점을 탭합니다 — 이며, 여기에는 Gemini **ER**(Embodied Reasoning / Robotics) 모델이 필요합니다. 동일한 탐지 프롬프트를 합성된 1080×2340 화면에서 Claude Sonnet으로 구동한 결과:

| 대상 | 평균 오차 | 정답 5% 이내 |
| --- | --- | --- |
| 크고 대비가 뚜렷한 도형 | 0.01 | 2/2 |
| 조밀한 설정 행과 토글 | 0.38 | 0/5 |

정규화 0.38은 수백 픽셀입니다. 엉뚱한 행을, 그것도 확신을 갖고 탭합니다. 계약을 다시 표현해도(위치 기반 `[y, x]` 배열 대신 이름 있는 `x`/`y` 필드) 구제되지 않습니다 — 0.33, 여전히 0/5. 그래서 ARTEMIS는 ER이 아닌 모델에서 탐지가 돌아가면 추측을 측정값으로 통과시키는 대신 경고를 남깁니다.

`pro` 티어는 하향 조정이 아니라 다른 메커니즘입니다. `ask_perception_tool`이 접근성/OCR 화면 인덱스를 퍼지 검색해 각 엘리먼트의 실제 `bounds`에서 계산한 좌표를 돌려주므로, 모델은 라벨이 붙은 후보 중 어느 것이 맞는지 고르기만 합니다. 픽셀을 추측하는 부분이 없고 비전 모델도 개입하지 않습니다. 키 없는 실행이 가능한 이유가 이것이며, ARTEMIS가 이미 액션의 85% 이상에서 쓰고 있는 경로이기도 합니다. (여기서 `ultra`는 쓰지 마세요 — 일회성 탐지와 Google Vision 키를 요구하는 OCR 도구를 다시 노출합니다.)

**포기하게 되는 것:** 접근성 노드를 내보내지 않는 커스텀 렌더링 UI(Canvas, Compose, Flutter). 그런 화면에서는 트리가 비어 있어 픽셀 그라운딩만이 동작합니다. 이런 화면이 꼭 필요하다면 `object_detector` 한 노드만 `gemini-robotics-er-2-preview`로 되돌리면 되고(배포된 설정에 해당 블록이 주석 처리되어 들어 있습니다), 그것이 Google 키를 둘 유일한 이유입니다.

**그 밖에 알아둘 점:**

* **레이트 리밋이 아니라 구독 윈도.** Pro 프로파일 실행은 수백 번의 모델 호출을 만듭니다. Claude CLI는 매 호출마다 5시간·7일 윈도를 보고하며, ARTEMIS는 90%를 넘으면 경고하고 윈도를 다 쓰면 해당 노드의 폴백으로 넘깁니다. `--profile flash`를 권장합니다.
* **비용은 대칭이 아닙니다.** `codex exec`에는 `--system-prompt`나 `--safe-mode`에 해당하는 것이 없어서, 매 호출마다 전체 코딩 에이전트 지시문을 함께 보냅니다. 동일 프롬프트 기준 실측:

  | 백엔드 | 호출당 입력 토큰 | 호출당 소요 시간 |
  | --- | --- | --- |
  | `claude_cli` | 약 1,200 | 약 1.6초 |
  | `codex_cli` | 약 27,800 | 약 13.4초 |

* **네이티브 도구 호출이 없습니다.** 두 CLI 모두 호출자에게 function calling을 노출하지 않으므로, 도구는 프롬프트 계약으로 주입하고 JSON 봉투에서 되파싱합니다 (Codex는 `--output-schema`로 이를 강제합니다).
* **API 키가 아니라 구독을 씁니다.** ARTEMIS는 CLI 환경에서 `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` 등을 제거하므로, `.env`에 남아 있는 키 때문에 호출이 조용히 종량제 API 과금으로 바뀌지 않습니다. 이 동작을 끄려면 `ARTEMIS_CLI_INHERIT_API_KEYS=1`을 설정하세요.
* **재귀가 없습니다.** 자식 프로세스는 `--safe-mode --tools "" --strict-mcp-config`로 실행되어 `CLAUDE.md`도, 스킬도, MCP 서버도 로드하지 않습니다 — `artemis mcp --install claude`가 설정하는 ARTEMIS MCP 서버도 포함이라, 자식이 다시 그쪽으로 호출해 들어가는 일이 없습니다.

</details>

<a id="python-sdk"></a>
<details>
<summary><b>Python SDK 연동 (클릭하여 펼치기)</b></summary>

<br>

런타임 의존성이 없는 클라이언트를 개발 머신에 설치하세요. ADB, 에이전트, 모델, 이미지 처리는 기기가 연결된 호스트에 그대로 남습니다:

```powershell
uv add "artemis-client @ git+https://github.com/google/artemis.git#subdirectory=packages/artemis-client"
```

```python
import asyncio
from artemis_client import ArtemisClient


async def main():
    client = ArtemisClient(
        "http://artemis-host:8000",
        device_serial="emulator-5554",  # optional: target specific device serial
        default_profile="flash",  # "flash" (fast reactive) or "pro" (deep reasoning)
    )

    result = await client.run(
        "Open System Settings, go to 'Battery', verify battery percentage is displayed, and check for any crash dialogs.",
    )

    assert result.succeeded, f"Test failed: {result.error or result.status}"
    print(f"✅ Test Passed! Device: {result.device_serial} | Trace ID: {result.trace_id}")


if __name__ == "__main__":
    asyncio.run(main())
```

</details>

## 사용 방식

<p align="center">
  <img src="./docs/assets/artemis-ui-showcase-en.png" alt="Artemis Web Console" width="100%" />
  <br />
  <sub><b>콘솔 구성</b>: <b>① 뷰 전환</b> (Home / Workspace) · <b>② 모델 및 리플레이</b> (Flash/Pro 상태와 영상 리플레이) · <b>③ 실시간 에이전트 스트림</b> (액션 인식, 대상 좌표, 구조화된 결과) · <b>④ 프롬프트 독</b> (자연어 태스크 발행) · <b>⑤ 태스크 큐 및 대시보드</b> (생명주기와 이력)</sub>
</p>

* **웹 시각 테스트 콘솔 (`uv run artemis ui`)**: 실시간 화면 투사와 인터랙티브 패널을 제공하며 자연어 테스트 발행, 실시간 추론 텔레메트리, 액션 궤적, 실행 리플레이를 지원합니다. 서버 생명주기는 어느 터미널에서든 `uv run artemis restart`, `uv run artemis stop`, `uv run artemis status`로 관리합니다.
* **MCP 서버**: **Antigravity, Claude Code, Windsurf** 등 MCP 클라이언트를 실기기에 연결해 버그 재현과 테스트 실행을 수행합니다.
* **개발자 CLI (`uv run artemis run`)**: 자동화 테스트 케이스, 탐색적 안정성 점검, AndroidWorld 벤치마크를 터미널에서 바로 실행하며 고품질 구조화 출력을 제공합니다.
* **Python SDK**: 기존 자동화 테스트 프레임워크(예: pytest)나 CI/CD 파이프라인에 표준 Python 라이브러리로 통합되며, 강타입 Pydantic 구조화 출력과 단언을 지원합니다.

<a id="on-device-helper"></a>
## ARTEMIS가 휴대폰에 설치하는 것

기기에서 첫 태스크를 실행하면 **Artemis Accessibility Helper**가 설치됩니다. UiAutomation 연결을 점유하지 않고 화면 레이아웃을 읽는 작은 접근성 서비스입니다. UiAutomation을 쓰는 도구들은 `FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`를 켜지 않는 한 이 헬퍼를 억제할 수 있습니다. 접힌 형태의 "Artemis test helper is running" 알림과 설정 > 접근성의 새 항목이 보이는데, 둘 다 이 헬퍼입니다. 휴대폰 내부에서만 수신하며 외부로 아무것도 보내지 않습니다.

* 미리 설치 (첫 태스크의 약 3초 지연 제거): `uv run artemis helper install`
* 상태 확인: `uv run artemis helper status` / `uv run artemis doctor`
* 언제든 제거: `uv run artemis helper uninstall`
* 대신 UIAutomator2 사용: `.env`에 `ARTEMIS_HIERARCHY_BACKEND=uiautomator`
* 자동 설치 방지: `.env`에 `ARTEMIS_HELPER_AUTO_INSTALL=false`

태스크 도중 헬퍼가 실패하면 ARTEMIS는 UIAutomator2로 폴백하고, 그 사실을 태스크 타임라인과 `mobile_manage_task` 상태, 최종 리포트에 남깁니다.

<a id="benchmarks"></a>
## 벤치마크: AndroidWorld (SOTA 99%+)

Artemis는 20개 이상의 앱과 100개 이상의 멀티스텝 태스크를 아우르는 Google Research의 벤치마크 [AndroidWorld](https://github.com/google-research/android_world)에서 **99%+ 완료율**을 달성했습니다.

<p align="center">
  <img src="./docs/assets/androidworld_leaderboard.png?v=2" alt="AndroidWorld Benchmark Comparison" width="100%" />
</p>

## ARTEMIS의 구조

* **실행 전 검증과 액션 버스트**: Pro는 개별 액션을 내보내기 전에 대상을 실시간 UI 트리와 픽셀로 검증합니다. 액션 버스트는 모델의 다음 턴을 기다리지 않고 순간적으로 나타나는 컨트롤을 처리합니다.
* **엘리먼트 위치 탐색**: 접근성 계층과 OCR을 결합하고, 커스텀 Canvas·Compose·Flutter 인터페이스에는 시각 모델을 함께 사용합니다.
* **공유 히스토리 압축**: Flash와 Pro는 오래된 스크린샷을 시각 요약으로 대체하고 완료된 스텝을 검색 가능한 히스토리 청크로 압축합니다. 원본 턴을 언제 대체할지는 컨텍스트 임계값으로 제어합니다.

<p align="center">
  <img src="./docs/assets/artemis_architecture_diagram.png" alt="ARTEMIS System Architecture Diagram" width="100%" />
</p>

## 실행 프로파일: Flash vs. Pro

ARTEMIS는 자동화 요구사항에 따라 두 가지 실행 프로파일을 제공합니다:

* **Flash 프로파일 (`--profile flash`)**: 빠르고 토큰 효율적인 반응 루프(스텝당 약 3~5초). 하나의 모델이 실시간 화면을 관측하고 사고하고 행동하며, 그래프 오케스트레이션이 없습니다. 정형적이고 결정적인 UI 작업에 적합합니다. 히스토리를 잘라내는 대신 압축하기 때문에 루프에는 기본적으로 상한이 없습니다(`agent.flash.max_turns`, 0 = 무제한). Flash는 Pro의 세션 트랜스크립트 원장을 공유하며(세션 기준 `T+mm:ss` 시계, 스크린샷은 시각 요약으로 접힘, 오래된 스텝은 시대 단위로 청크되어 `search_history` / `replay_steps`로 필요할 때 소환 가능), `video_analyzer`로 세션 녹화를 조회할 수 있습니다. 자동으로 사라지는 컨트롤 바나 토스트 같은 순간적 UI는 탭을 하나의 `click_sequence`로 이어 붙여 처리합니다. *제약*: 태스크 계획과 노트 없음, 실행 전 안전망 없음, 체크포인트 검증과 최종 리포트 없음, ADB 셸 없음.
* **Pro 프로파일 (`--profile pro`)**: 계획과 검증을 포함하는 워크플로(스텝당 약 15~40초)로, 멀티 에이전트 그래프로 구성됩니다. **Planner**가 마일스톤과 `verify` / `assert` 체크 항목을 갖춘 살아 있는 Markdown 태스크 계획을 유지하고, **Operator**가 전체 도구셋으로 이를 실행합니다 (Explorer 그라운딩의 `flash` / `pro` / `ultra` 티어는 프로파일별 사용자 설정입니다 — `config/artemis.jsonc`의 `pro.explorer.mode` / `flash.explorer_mode` 또는 `--explorer-pro-mode` — 에이전트가 고르지 않습니다. 그 외 노트, 히스토리 소환, 영상 분석, ADB 진단). 단일 액션은 모두 실행 전 **안전망**(XML 우선, 픽셀 폴백)을 통과하며, 여러 액션으로 이루어진 **fast-action 버스트**는 순간적 UI에서 턴 지연을 이기기 위해 연속으로 발사됩니다. 차단되거나 실패한 액션은 **실행 인시던트**를 열고 이후 액션이 성공할 때까지 Operator의 컨텍스트에 남으므로, 복구는 별도 수리 에이전트 없이 Operator가 직접 수행합니다. 읽기 전용 **Checker**가 계획의 체크포인트를 검증하고 원래 목표에 대한 종료 최종 리뷰를 수행하며(`--verification-level`: `off` / `final`(기본) / `checkpoints` / `strict`), 계획 마일스톤 수정에는 권고성 리뷰가 붙습니다. 100스텝 이상의 장기 워크플로, `[Loop:continuous]` 모니터링, 선택적 서면 리포트를 처리합니다.

## 로드맵

- [ ] **Android Studio 통합**: 네이티브 IDE 플러그인과 워크플로 통합으로 Android Studio 안에서 바로 디버깅, 테스트 레코딩, 자동 기기 제어를 지원합니다.
- [ ] **iOS 플랫폼 확장**: 멀티모달 인식과 모바일 자동화를 iOS 실기기와 시뮬레이터로 확장합니다.
- [ ] **온디바이스 경량 VLM**: 저지연·프라이버시 우선 자동화를 위한 경량 엣지 비전 모델의 로컬 실행을 지원합니다.
- [ ] **실시간 양방향 음성 인터랙션**: 음성으로 태스크를 발행하고 실시간 대화형 제어와 끼어들기를 처리합니다.

## 커뮤니티 및 기여

기여를 언제나 환영합니다!
* 업데이트와 릴리스를 따라가려면 **저장소에 Star**를 눌러 주세요
* 기술 논의는 [Discord 커뮤니티](https://discord.gg/wF2FN4WHGY)에서 나눕니다
* [Issue](https://github.com/google/artemis/issues)를 열거나 [Pull Request](https://github.com/google/artemis/pulls)를 보내 주세요

## 라이선스

이 프로젝트는 [Apache License 2.0](LICENSE)을 따릅니다.

이 프로젝트에는 [Minitap, Inc.](https://github.com/minitap-ai/mobile-use)가 개발한 소스 코드가 포함되어 있습니다.
