# 정적 센서·렌즈 프로파일

내장 카탈로그는 Workbook 계산과 비교 화면에 규격값을 공급한다. 프로그램은
카메라를 검색·연결·설정하거나 프레임을 취득하지 않는다. 부품 구매나 마운트
가공 전에는 반드시 제조사의 최신 제품 페이지와 도면을 다시 확인한다.

## Basler 센서 프로파일

| 정적 프로파일 | 활성 픽셀 | 픽셀 피치 | 활성 크기 | 문서상 최대 속도 | 인터페이스 | 마운트 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| ace acA1300-60gm | 1282 × 1026 | 5.3 µm | 6.7946 × 5.4378 mm | 60 fps | GigE | C |
| dart daA1280-54um | 1280 × 960 | 3.75 µm | 4.8000 × 3.6000 mm | 54 fps | USB3 | S |
| dart dmA2048-37gm | 2064 × 1552 | 2.25 µm | 4.6440 × 3.4920 mm | 기본 32.6 fps, 성능 설정 37.2 fps | GigE | 모델 변형별 확인 |
| dart daA2448-70um | 2448 × 2048 | 2.74 µm | 6.7075 × 5.6115 mm | 기본 29.8 fps, 링크 제한 해제 시 72.8 fps | USB3 | S |

`acA1300-60gm`의 활성 크기는 Workbook 회귀에 사용한
6.7946 × 5.4378 mm와 일치한다. 모델을 선택하면 다음 값만 바뀐다.

- 활성 해상도와 픽셀 피치
- 가로·세로 활성 길이
- 선택 축의 기하 FOV와 평균 샘플링
- 근거리·중앙·원거리 및 최악 기하 거리 민감도

여기서 거리 민감도는 센서 1 pixel 이동에 대응하는 이상적인 물체측 거리
변화량이다. 양자효율, 감도, 신호대잡음비나 최소 조도와 같은 카메라의
광전기 성능을 뜻하지 않는다.

공식 정적 규격 출처:

- [Basler ace acA1300-60gm](https://docs.baslerweb.com/aca1300-60gm)
- [Basler dart daA1280-54um](https://docs.baslerweb.com/daa1280-54um)
- [Basler dart dmA2048-37gm](https://docs.baslerweb.com/dma2048-37gm)
- [Basler dart daA2448-70um](https://docs.baslerweb.com/daa2448-70um)

## Edmund Optics M12 렌즈 프로파일

초점거리 선택용 정적 후보는 다음과 같다.

| SKU | 명칭 | 초점거리 | 상세 외형/주평면 데이터 |
| --- | --- | ---: | --- |
| #33-879 | UCi Series | 12 mm | 미등록 값은 추정하지 않음 |
| #83-953 | Blue Series | 12.5 mm | 미등록 값은 추정하지 않음 |
| #36-376 | Ruggedized Blue Series | 16 mm | 미등록 값은 추정하지 않음 |
| #58-206 | Blue Series f/2.5 | 17.5 mm | 공식 제품 페이지·DWG 58206 반영 |
| #83-954 | Blue Series f/8 | 17.5 mm | 공식 제품 페이지·DWG 83954 반영 |
| #36-385 | Ruggedized Blue Series | 25 mm | 미등록 값은 추정하지 않음 |
| #70-646 | Blue Series | 35 mm | 미등록 값은 추정하지 않음 |

### 공식 카탈로그와 프로젝트 사용자 프리셋

내장 Edmund 항목은 출처가 있는 기준 프로파일이며 실행 중 수정하거나 같은
ID로 덮어쓰지 않는다. 사용자가 실제 보유 렌즈나 조립 측정값을 반영하려면
공식 항목을 복제하거나 출처 없는 빈 항목으로 프로젝트 사용자 프리셋을 만든다. 사용자 항목은 별도의
`user-lens:` ID 공간을 사용하므로 공식 SKU와 충돌하지 않는다.

사용자 프리셋에서는 초점거리와 조리개값, 이미지 서클, 파장·WD·BFL 범위,
해상력, 마운트, 외경과 길이, 하우징 단차·나사부, 첫 광학면 recess,
`S1→H`와 `SL→H′`를 수정할 수 있다. 기존
사용자 프리셋은 다시 편집하거나 삭제할 수 있지만, 이 작업은 현재
`.scheimpflug.json` 안의 복사본에만 적용된다.

H/H′ 오프셋은 부호 있는 광축 좌표이며 기준면은 고정된다.

- `S1→H`: 물체측 첫 번째 광학면 `S1` 기준
- `SL→H′`: 상측 마지막 광학면 `SL` 기준

하우징 면이나 센서면을 이 두 값의 datum으로 대신 사용하면 안 된다. 또한
필수 기구 치수나 `S1→H` 중 하나라도 없거나 `L_front + L_thread`와
`OAL`의 관계가 허용 범위를 벗어나면 실치수 3D 외형을 비활성화한다. 누락
치수를 0 또는 추정값으로 채워 실제 형상처럼 표시하지 않는다. 광학 전용
프리셋은 초점거리를 이용한 Workbook 계산에는 계속 사용할 수 있다.
사용자 항목은 복제 원본이 있더라도 편집 후 공급사 검증 사양이나 공식 도면으로
표시하지 않는다. 원본 ID는 유래 추적용일 뿐 현재 사용자 수치의 검증 표식이
아니다.

### Workbook 참조 부품 식별

원본 Workbook에 적힌 `58206_002`는 **#58-206 17.5 mm f/2.5** 계열을
가리킨다. **#83-954는 17.5 mm f/8**이며 초점거리가 같더라도 서로 다른
SKU다. 프로그램은 이 둘을 같은 렌즈로 합치지 않고 출처를 구분해 표시한다.

### 검증된 #58-206 / #83-954 데이터

| 항목 | #58-206 | #83-954 |
| --- | ---: | ---: |
| F-number | f/2.5 | f/8 |
| 이미지 서클 | 9.00 mm | 9.00 mm |
| 파장 범위 | 400–700 nm | 400–700 nm |
| 권장 WD | 150 mm–∞ | 150 mm–∞ |
| 외경 | 14.00 mm | 14.00 mm |
| 전체 길이 | DWG 기준 20.68 mm | 20.70 mm |
| 전면 하우징 길이 | 7.60 mm | 7.60 mm |
| M12 나사부 길이 | 13.08 mm | 13.10 mm |
| 전면 하우징→첫 광학면 | 0.30 mm | 0.12 mm |
| 첫 물체측 광학면→H | +5.57 mm | +5.57 mm |
| 마지막 이미지측 광학면→H′ | −12.71 mm | −12.71 mm |
| BFL | 4.9–5.8 mm | 4.9–5.8 mm |

계산된 물체측 주평면 `H`에서 렌즈 외형의 전면을 역산할 때 사용하는 거리는
각각 다음과 같다.

```text
#58-206: front housing → H = 0.30 + 5.57 = 5.87 mm
#83-954: front housing → H = 0.12 + 5.57 = 5.69 mm
```

공급사의 `H′=−12.71 mm`는 마지막 이미지측 광학면을 기준으로 한 값이다.
공식 외형 데이터에는 그 마지막 광학면과 하우징 후면 사이의 절대 위치가
없으므로 하우징 기준 H′ 위치와 실제 주평면 간격 `e`는 추정하지 않는다.
Workbook 계산 자체도 H/H′ 수치 분리가 없는 얇은 렌즈 모델이다.

공식 제품·기계 도면 출처:

- [Edmund Optics #58-206 제품 페이지 및 DWG 58206](https://www.edmundoptics.com/p/175mm-fl-f25-blue-series-m12-mu-videotrade-imaging-lens/15122/)
- [Edmund Optics #83-954 제품 페이지 및 DWG 83954](https://www.edmundoptics.com/p/175mm-fl-f8-blue-series-m12-mu-videotrade-imaging-lens/27055/)
- [Edmund Optics #33-879 검색](https://www.edmundoptics.com/search/?criteria=33-879)
- [Edmund Optics #83-953 검색](https://www.edmundoptics.com/search/?criteria=83-953)
- [Edmund Optics #36-376 검색](https://www.edmundoptics.com/search/?criteria=36-376)
- [Edmund Optics #36-385 검색](https://www.edmundoptics.com/search/?criteria=36-385)
- [Edmund Optics #70-646 검색](https://www.edmundoptics.com/search/?criteria=70-646)

M12×0.5에는 보편적인 플랜지 거리가 없다. C-to-M12 어댑터는 마운트만
바꾸며 Scheimpflug 기울기를 만들지 않는다. 시뮬레이션의 외형 표시는
간섭 검토를 돕기 위한 것이며 실제 조립 검증이나 안전성 보증이 아니다.
