# Scheimpflug OptiMeter

`구조설계_rev.1.xlsx`에서 사용하던 입력·수식·결과를 데스크톱 화면으로 옮기고,
계산값에 따른 Scheimpflug 레이저 삼각측량 구조를 실시간으로 확인하는 Python
3.12 프로그램입니다. 논문은 계산식과 광학 해석을 검증하기 위한 참고자료이며,
논문에 등장하는 실험 시스템 전체를 재현하는 것이 이 프로그램의 목표는 아닙니다.

제공된 연구 논문과 `구조설계_rev.1.xlsx`는 로컬 참고자료이며 이 공개
저장소에는 포함하지 않습니다.

## 주요 기능

- 워크북/XLSX에서 추출한 `V, d, L, α` 입력과 수식을 재현하는 기본 계산
- 사용자 `L` 직접 입력과 한 행 CSV 입력·전체 계산 결과 내보내기
- 계산 즉시 갱신되는 레이저 직선, 워킹 디스턴스, 렌즈 및 이미지 평면
- 정확한 비대칭 센서 결상 구간과 논문식 패키지 근사의 동시 표시
- Basler acA1300-60gm 1.3MP 및 dart 1.2/3.2/5MP 하드웨어 프로파일
- Edmund Optics M12×0.5 렌즈 후보와 장착·이미지 서클 호환성 검사
- 카메라 없이 실행 가능한 최신 프레임 방식 모의 카메라
- schema-v1 `.scheimpflug.json`, SVG/PNG/CSV 내보내기
- 고급/연구 참고로 분리된 canonical 계산, 최적화, 3D, 보정 및 단면 측정

## 빠른 실행

64비트 Python 3.12.10 이상이 필요하며 Python 3.13은 지원하지 않습니다.

```powershell
uv sync --extra dev
uv run scheimpflug-optimeter
uv run pytest
```

`uv`를 사용하지 않을 경우:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\scheimpflug-optimeter.exe
```

Basler 카메라 지원은 선택 사항입니다.

```powershell
uv sync --extra dev --extra camera
```

Basler pylon runtime과 GigE/USB transport driver는 별도로 설치해야 합니다.
카메라 SDK가 없어도 기본 워크북 계산·2D 시각화와 고급 설계 기능은 실행됩니다.

첫 실행에는
[`examples/acA1300-60gm-12mm.scheimpflug.json`](examples/acA1300-60gm-12mm.scheimpflug.json)
샘플 프로젝트를 사용할 수 있습니다.

## Windows 포터블 ZIP

GitHub Release의 `Scheimpflug-OptiMeter-windows-x64.zip`을 내려받아 전체 폴더를
압축 해제한 다음 `Scheimpflug-OptiMeter.exe`를 실행합니다. `_internal` 폴더는
실행 파일과 같은 위치에 그대로 두어야 합니다. Python을 별도로 설치하지 않아도
워크북 계산, 광학 시각화와 모의 카메라를 사용할 수 있습니다.

표준 포터블 ZIP은 SDK가 없는 PC에서도 시작하도록 `pypylon`을 포함하지 않습니다.
실제 Basler 카메라를 연결할 때는 Basler pylon runtime/드라이버를 설치하고 위의
소스 실행 환경에 `--extra camera`를 추가하십시오. 릴리스에는 사용자 설명서,
하드웨어·보정 문서, 샘플 프로젝트 및 ZIP의 SHA-256 파일이 함께 제공됩니다.
소스 ZIP과 tarball은 GitHub Release에서 자동으로 제공됩니다.
현재 자동 빌드 실행 파일은 코드 서명되지 않으므로, 배포 파일을 사용할 때는
동봉된 SHA-256 값을 먼저 확인하십시오.

## 문서

- [Architecture](docs/architecture.md)
- [Optical formulas](docs/formulas.md)
- [Optimization](docs/optimization.md)
- [Hardware integration](docs/hardware.md)
- [Calibration and acceptance](docs/calibration.md)
- [User guide](docs/user-guide.md)
- [Research references](docs/references.md)

## 하드웨어 주의사항

`acA1300-60gm`은 C-mount 카메라입니다. M12 렌즈를 사용하려면 어댑터가
필요하며, 마운트 어댑터와 Scheimpflug 센서/렌즈 틸트 기구는 서로 다른
부품입니다. M12×0.5에는 단일 표준 플랜지 거리가 없으므로 실제 조립 후
반드시 보정하고 독립된 기준물로 검증해야 합니다.

이 소프트웨어의 계산값은 기구 간섭, 레이저 안전 또는 계측 정확도를
자동으로 보증하지 않습니다.
