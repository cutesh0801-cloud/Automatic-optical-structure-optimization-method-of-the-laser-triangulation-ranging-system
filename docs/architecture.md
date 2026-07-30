# 아키텍처

Scheimpflug OptiMeter는 Windows용 PySide6 Workbook 계산·시각화
애플리케이션과 작은 수치 코어로 구성된다. 사용자 화면은
`구조설계_rev.1.xlsx` 계산 경로 하나만 제공한다.

```text
Workbook 형식 입력 시트
  └─ Workbook solver
       ├─ 단일 DesignSolution ── 결과표
       ├─ SceneGeometry ──────── 실시간 2D / 보조 3D
       └─ 정적 Basler 규격 ───── FOV / 샘플링 / 거리 민감도 비교

정적 Edmund 렌즈 규격
  ├─ 변경 불가 공식 프로파일
  └─ 복제 ── 프로젝트 사용자 렌즈 프리셋
                ├─ 초점거리 선택
                ├─ H 기준 외형 위치 역산
                └─ 완전한 기구 자료일 때만 실치수 3D

프로젝트 JSON / CSV 입력·출력 / PNG·SVG + snapshot JSON
```

카메라 장치 I/O 경계는 없다. 프로그램은 카메라를 열거·연결하거나 프레임을
취득하지 않으며, 영상 보정·레이저 선 검출·단면 측정도 수행하지 않는다.
Basler 모델명은 정적 센서 규격을 선택하기 위한 ID다.

## 경계와 단일 계산 원천

- 단위가 포함된 필드명을 가진 frozen/slots dataclass를 사용한다.
- 광학 수식은 UI 밖의 결정론적 순수 함수에서만 계산한다.
- 하나의 `DesignSolution`과 `SceneGeometry`가 결과표, 2D, 3D와 센서 비교에
  공급된다.
- UI는 같은 수식을 복제하지 않고 계산 결과의 이름 있는 좌표를 표시한다.
- Qt signal/slot을 직접 사용하며 별도 이벤트 버스나 상태관리 프레임워크가 없다.
- 프로젝트는 버전이 있는 JSON이며 데이터베이스가 없다.
- 프로젝트 파일의 입력만 권위가 있고 파생값은 로드할 때 다시 계산한다.
- 정적 카탈로그 조회는 어떤 장치 접근도 시작하지 않는다.
- 공식 렌즈 카탈로그는 불변이며 사용자 수정은 프로젝트 전용 복사본에만
  기록한다.

## Workbook 좌표계

렌더러는 한 개의 world-to-screen 축척을 사용하므로 광학 각도를 화면에 맞춰
임의로 찌그러뜨리지 않는다.

```text
T = (0,0)       Zero position / 기준점
E = (0,V)       레이저 발광점
I = (b,V)       CMOS 이미지 중심
u = (sinα,cosα) 수광축 단위벡터
H = T + l₀u
H′ = H          Workbook thin-lens
```

CMOS 평면은 `z=V`인 수평선이며 수직 레이저축과 직교한다. `β=90°−α`는
수광축과 CMOS 사이의 유도 보각이지 CMOS tilt가 아니다. 렌즈 평면은 H를
지나고 수광축 `u`에 직교한다.

2D scene은 레이저축, 기준점과 WD, 수광축, chief ray, 렌즈·CMOS 평면,
Scheimpflug 교점, `W/R` 외곽과 먼 `s` 교점을 표시한다. 아주 먼 교점은
광학 헤드 축척을 망가뜨리지 않도록 화면 경계 표기로 분리한다.

## H 기준 렌즈 외형

Workbook 광학식에는 두꺼운 렌즈의 H/H′ 분리값이 없으므로 계산
`SceneGeometry`는 H와 H′를 같은 렌즈점으로 둔다.

외형 렌더링은 이 광학 가정을 바꾸지 않는다. 공급사에서 전면 하우징 datum,
첫 물체측 광학면 recess와 `S₁→H`를 모두 제공한 렌즈만 다음처럼 배치한다.

```text
F₀ = H − (recess + S₁→H)u
step = F₀ + front_housing_length·u
rear = F₀ + overall_length·u
```

#58-206은 `F₀→H=5.87 mm`, #83-954는 `F₀→H=5.69 mm`다. 공급사의 H′는
마지막 이미지측 광학면 기준인데 하우징에 대한 그 광학면의 절대 datum이
없으므로 실제 H′ 좌표와 주평면 간격 `e`를 만들지 않는다.

사용자 렌즈 프리셋도 같은 원칙을 따른다. 편집 가능한 주평면 값의 의미는
다음 두 종류로 고정한다.

```text
object_principal_plane_from_first_object_surface_mm = S1→H
object_principal_plane_datum = first_object_surface

image_principal_plane_from_last_image_surface_mm = SL→H′
image_principal_plane_datum = last_image_surface
```

두 오프셋은 부호 있는 광축 좌표다. 하우징이나 센서 datum으로 재해석하지
않으며, Workbook 해법의 `H=H′`를 두꺼운 렌즈 해법으로 바꾸지도 않는다.
물체측 `S1→H`와 `Front→S1`이 있으면 계산된 H에서 하우징 전면을 역산할 수
있다. 반대로 하우징에 대한 `SL`의 위치가 없으면 `SL→H′`만으로 실제 H′의
절대 world 좌표를 만들 수 없으므로 만들지 않는다.

실치수 렌더링은 외경, 전체 길이, 전면 하우징과 나사부 길이, 나사 지름·피치,
`Front→S1`, `S1→H`가 모두 있고 내부 길이 검증을 통과한 경우에만 켠다.
자료가 불완전하거나 모순되면 광학 계산용 초점거리는 사용할 수 있지만 물리
렌즈 외형은 비활성화한다.

## 사용자 렌즈 프리셋 저장 경계

`UserLensPreset`은 frozen/slots 값 객체이며 공식 `LensProfile`을 변경하지
않는다. 공식 항목을 복제하면 `user-lens:<user_id>` 런타임 ID를 발급하고,
기존 사용자 항목을 편집할 때는 프로젝트 안의 안정적인 `user_id`를 유지한다.
빈 프리셋은 공급사 provenance 없이 시작한다. 공식 항목을 복제한 경우에도
사용자 저장 시 공식 도면 ID·도면 URL·검증일을 제거하고 원본 프로파일 ID만
유래 추적용으로 남겨, 수정값을 공식 검증값처럼 표시하지 않는다.

프리셋 컬렉션은 프로젝트 schema 1의
`design_input.user_lens_presets`에 자체 schema version과 함께 저장된다.
프로젝트 밖의 전역 설정 파일이나 데이터베이스는 만들지 않는다. 열 때
컬렉션과 각 프리셋을 검증하며, 지원하지 않는 schema, 잘못된 datum, 유한하지
않은 수치 또는 필수 광학값 오류는 조용히 보정하지 않고 로드를 거부한다.
선택한 사용자 렌즈 ID와 컬렉션, 카메라·센서축·공식 렌즈 참조를 모두 임시
상태에서 검증한 뒤 한 번에 UI에 반영하므로 실패한 프로젝트 열기가 현재
프로젝트 상태 일부를 바꾸지 않는다.

## UI와 실행 특성

- 입력 변경은 16 ms debounce 후 GUI thread에서 Workbook 계산과 2D 항목
  재배치를 수행한다.
- 2D는 기존 `QGraphicsItem`을 재사용한다.
- NumPy/Matplotlib와 3D canvas는 3D 탭을 처음 열 때 지연 로드한다.
- 입력 오류가 생기면 파생 결과와 장면을 무효화하며 이전 정상 결과를 현재
  결과처럼 유지하지 않는다.
- 최적화 작업 thread나 장치 획득 thread는 현재 사용자 경로에 없다.

## 비노출 연구·호환 코드

일부 모듈에는 논문 비교용 canonical 계산과 최적화 API, 과거 프로젝트
schema의 필드가 남아 있을 수 있다. 이 코드는 메인 창에서 선택하거나 실행할
수 없는 연구·호환용 내부 경계이며 현재 제품 기능, UI 흐름 또는 릴리스 완료
조건이 아니다. Workbook UI는 과거 canonical 값을 현재 Workbook 입력으로
조용히 재해석하지 않는다.
