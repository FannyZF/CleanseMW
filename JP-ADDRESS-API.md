# 日本流向地址清洗 API 接口文档

**版本**: 2.0  
**Base URL**: `http://101.32.239.62:18933/api/v1`

---

## 目录

- [通用说明](#通用说明)
- [1. 单条地址清洗](#1-单条地址清洗)
- [2. 批量地址清洗](#2-批量地址清洗)
- [3. Excel 批量上传](#3-excel-批量上传)
- [4. Excel 结果下载](#4-excel-结果下载)
- [状态码与错误](#状态码与错误)
- [地址验证精度说明](#地址验证精度说明)
- [清洗流程](#清洗流程)

---

## 通用说明

### 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Content-Type` | 是 | `application/json`（Excel 上传除外） |
| `X-API-Key`    | 是 | 由系统管理员分配的唯一 API 密钥，格式 `ch_xxxx...` |

### 批量请求

单条接口支持自动批量：若 body 为数组 `[{...}, {...}]`，系统自动识别为批量请求，上限 **100 条**。

### 数据完整性

每个响应自动包含 `request_hash` 和 `response_hash`（SHA256 指纹），可用于争议时验证数据是否被篡改。

### 日本邮编格式

支持以下任意输入格式，系统自动标准化：
- `1600023`（7位数字）
- `160-0023`（带连字符）
- `〒160-0023`（带邮编符号）

---

## 1. 单条地址清洗

```
POST /jp/cleanse/address           (推荐)
POST /cleanse/address              (兼容旧版)
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id`          | string | 否 | 订单号/运单号，未提供时系统自动生成唯一 ID |
| `raw_address`       | string | **是** | 原始地址，支持日文/英文/中文 |
| `provided_zipcode`  | string | **是** | 用户提供的日本邮编 |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"success"` |
| `reference_id` | string | 请求唯一标识（订单号或自动生成） |
| `data.address.is_valid` | boolean | 地址是否通过验证 |
| `data.address.validation_level` | string | 验证精度等级（见[精度说明](#地址验证精度说明)） |
| `data.address.verdict_level` | string | 寄递建议：`reliable` / `trusted` / `review` / `unreliable` |
| `data.address.verdict_message` | string | 中文判定说明 |
| `data.address.japanese_address` | string | 标准化后的日文地址 |
| `data.address.english_address` | string | 标准化后的英文地址 |
| `data.zipcode.match` | boolean | 邮编是否匹配 |
| `data.zipcode.provided` | string | 用户提供的原始邮编 |
| `data.zipcode.suggested_correct` | string\|null | 建议的正确邮编（不匹配时返回） |

### 请求示例

```json
POST /jp/cleanse/address
Content-Type: application/json
X-API-Key: ch_your_api_key_here

{
  "order_id": "SF-001",
  "raw_address": "160-0023 东京都新宿区西新宿2-8-1 501号室",
  "provided_zipcode": "160-0023"
}
```

### 响应示例（验证成功）

```json
{
  "status": "success",
  "reference_id": "SF-001",
  "data": {
    "address": {
      "is_valid": true,
      "validation_level": "PREMISE",
      "verdict_level": "reliable",
      "verdict_message": "地址精确到门牌号，可用于寄递",
      "japanese_address": "東京都新宿区西新宿2丁目8-1 501号室",
      "english_address": "2-8-1 Nishishinjuku, Shinjuku City, Tokyo 501号室"
    },
    "zipcode": {
      "match": true,
      "provided": "160-0023",
      "suggested_correct": null
    }
  },
  "request_hash": "sha256:a1b2c3...",
  "response_hash": "sha256:d4e5f6..."
}
```

### 响应示例（邮编不匹配）

```json
{
  "status": "success",
  "reference_id": "SF-002",
  "data": {
    "address": {
      "is_valid": true,
      "validation_level": "PREMISE",
      "verdict_level": "reliable",
      "verdict_message": "地址精确到门牌号，可用于寄递",
      "japanese_address": "東京都新宿区西新宿2丁目8-1",
      "english_address": "2-8-1 Nishishinjuku, Shinjuku City, Tokyo"
    },
    "zipcode": {
      "match": false,
      "provided": "160-0001",
      "suggested_correct": "160-0023"
    }
  },
  "request_hash": "sha256:...",
  "response_hash": "sha256:..."
}
```

### 响应示例（验证失败）

```json
{
  "status": "success",
  "reference_id": "SF-003",
  "data": {
    "address": {
      "is_valid": false,
      "validation_level": "UNKNOWN",
      "verdict_level": "unreliable",
      "verdict_message": "地址验证失败，需人工核实",
      "japanese_address": "存在しない住所123",
      "english_address": "存在しない住所123"
    },
    "zipcode": {
      "match": false,
      "provided": "000-0000",
      "suggested_correct": null
    }
  },
  "request_hash": "sha256:...",
  "response_hash": "sha256:..."
}
```

---

## 2. 批量地址清洗

### 方式一：数组自动批量

发送 JSON 数组，系统自动识别为批量请求：

```
POST /jp/cleanse/address
```

**请求：**
```json
[
  {
    "order_id": "SF-001",
    "raw_address": "160-0023 东京都新宿区西新宿2-8-1",
    "provided_zipcode": "160-0023"
  },
  {
    "order_id": "SF-002",
    "raw_address": "530-0002 大阪府大阪市北区曽根崎新地1-1-1",
    "provided_zipcode": "530-0002"
  }
]
```

**响应：**
```json
{
  "status": "success",
  "results": [
    {
      "reference_id": "SF-001",
      "data": {
        "address": { "is_valid": true, "validation_level": "PREMISE", "verdict_level": "reliable", "verdict_message": "地址精确到门牌号，可用于寄递", "japanese_address": "東京都新宿区西新宿2丁目8-1", "english_address": "2-8-1 Nishishinjuku, Shinjuku City, Tokyo" },
        "zipcode": { "match": true, "provided": "1600023", "suggested_correct": null }
      }
    },
    {
      "reference_id": "SF-002",
      "data": {
        "address": { "is_valid": true, "validation_level": "PREMISE", "verdict_level": "reliable", "verdict_message": "地址精确到门牌号，可用于寄递", "japanese_address": "大阪府大阪市北区曽根崎新地1丁目1-1", "english_address": "1-1-1 Sonezakishinchi, Kita-ku, Osaka" },
        "zipcode": { "match": true, "provided": "5300002", "suggested_correct": null }
      }
    }
  ]
}
```

> 上限 100 条，超出部分自动截断。

### 方式二：显式批量接口

```
POST /jp/cleanse/address/batch     (推荐)
POST /cleanse/address/batch        (兼容旧版)
```

**请求：**
```json
{
  "items": [
    { "order_id": "SF-001", "raw_address": "160-0023 东京都新宿区西新宿2-8-1", "provided_zipcode": "160-0023" },
    { "order_id": "SF-002", "raw_address": "530-0002 大阪府大阪市北区曽根崎新地1-1-1", "provided_zipcode": "530-0002" }
  ]
}
```

**响应：** 同方式一。

---

## 3. Excel 批量上传

上传含地址列的 Excel 文件，系统自动清洗并返回结构化审核数据。

```
POST /jp/cleanse/address/upload
```

### 请求

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | **是** | `.xlsx` / `.xls` 格式，上限 10MB |
| `prefecture_col` | string | 否 | 手工指定"県/都道府県"所在列名（不指定时自动检测） |
| `city_col`       | string | 否 | 手工指定"市"所在列名 |
| `ward_col`       | string | 否 | 手工指定"区/町"所在列名 |
| `address_col`    | string | 否 | 手工指定"具体地址/住所"所在列名 |
| `zip_col`        | string | 否 | 手工指定"邮编/郵便番号"所在列名 |
| `tracking_col`   | string | 否 | 手工指定"运单号"所在列名 |

### Excel 表头自动识别

系统根据别名自动匹配列，支持中/日/英文表头：

| 列含义 | 识别的表头别名 |
|--------|---------------|
| 都道府県 | `県` / `prefecture` / `都道府県` / `pref` / `ken` / `todofuken` |
| 市区     | `市` / `city` / `市区` / `city_name` / `shi` |
| 区/町    | `区` / `ward` / `district` / `町` / `町域` / `cho` / `machi` / `ku` |
| 具体地址 | `具体地址` / `address` / `住所` / `番地` / `detail` / `street` / `address_detail` |
| 邮编     | `邮编` / `zip` / `zipcode` / `郵便番号` / `postal_code` / `postal` |
| 运单号   | `运单号` / `tracking` / `運送番号` / `追跡番号` / `waybill` / `tracking_no` |

> 必填列：**具体地址** + **邮编**。若无法自动识别，返回 400 错误提示。

### 请求示例（curl）

```bash
curl -X POST http://101.32.239.62:18933/api/v1/jp/cleanse/address/upload \
  -H "X-API-Key: ch_your_api_key_here" \
  -F "file=@addresses.xlsx"
```

### 响应

```json
{
  "status": "success",
  "headers": {
    "prefectureCol": "県",
    "cityCol": "市",
    "wardCol": "区",
    "addressCol": "具体地址",
    "zipCol": "邮编"
  },
  "rows": [
    {
      "refId": "uuid-xxxx",
      "pref": "東京都",
      "city": "新宿区",
      "ward": "",
      "addr": "西新宿2-8-1",
      "zip": "1600023",
      "tracking": "SF1234567890",
      "status": "verified",
      "validationLevel": "PREMISE",
      "message": "地址精确到门牌号，可用于寄递",
      "dashSegments": [],
      "fullAddr": "東京都 新宿区 西新宿2-8-1",
      "validatedBase": "東京都新宿区西新宿2丁目8-1",
      "validatedPref": "東京都",
      "validatedCity": "新宿区",
      "validatedWard": "",
      "validatedStreet": "西新宿2丁目8-1",
      "validatedZip": "1600023",
      "validatedFull": "東京都新宿区西新宿2丁目8-1",
      "correction": "東京都新宿区西新宿2丁目8-1"
    }
  ]
}
```

### 响应字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `refId` | string | 行唯一标识 |
| `status` | string | 验证状态：`verified` / `review_other` / `blocked` / `error` |
| `validationLevel` | string | 验证精度等级 |
| `message` | string | 判定说明 |
| `validatedFull` | string | 验证后完整日文地址 |
| `validatedPref` | string | 验证后都道府県 |
| `validatedCity` | string | 验证后市 |
| `validatedWard` | string | 验证后区 |
| `validatedStreet` | string | 验证后街/番地 |
| `validatedZip` | string | 验证后邮编 |
| `correction` | string | 建议修正后的完整地址 |

### 状态定义

| status | 说明 |
|--------|------|
| `verified` | 地址验证通过，直接可用 |
| `review_other` | 邮编匹配但地址无法精确匹配，建议人工核实 |
| `blocked` | 地址验证失败 |
| `error` | 处理异常或必填字段缺失 |

---

## 4. Excel 结果下载

将审核/修正后的行数据导出为 Excel 文件。

```
POST /jp/cleanse/address/download
```

### 请求参数

```json
{
  "rows": [
    {
      "tracking": "SF1234567890",
      "pref": "東京都",
      "city": "新宿区",
      "ward": "",
      "addr": "西新宿2-8-1",
      "zip": "1600023",
      "status": "verified",
      "validationLevel": "PREMISE",
      "validatedFull": "東京都新宿区西新宿2丁目8-1",
      "validatedZip": "1600023",
      "correction": "東京都新宿区西新宿2丁目8-1",
      "_modified": false
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rows` | array | **是** | 审核/修正后的行数据（通常来自上传返回结果，用户可修改后回传） |

### rows 元素字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tracking` | string | 否 | 运单号 |
| `pref` | string | 否 | 県/都道府県（原始） |
| `city` | string | 否 | 市（原始） |
| `ward` | string | 否 | 区（原始） |
| `addr` | string | 否 | 具体地址（原始） |
| `zip` | string | 否 | 邮编（原始） |
| `status` | string | 否 | 验证状态 |
| `validationLevel` | string | 否 | 验证精度 |
| `validatedFull` | string | 否 | 验证后完整日文地址 |
| `validatedZip` | string | 否 | 验证后邮编 |
| `correction` | string | 否 | 修正后地址 |
| `_modified` | boolean | 否 | 是否经人工修改 |

### 响应

返回 `.xlsx` 文件（`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`）。

**输出 Excel 列：**

| 列名 | 说明 |
|------|------|
| 运单号 | 原始运单号 |
| 県（原始） | 原始都道府県 |
| 市（原始） | 原始市 |
| 区（原始） | 原始区 |
| 具体地址（原始） | 原始地址 |
| 邮编（原始） | 原始邮编 |
| 验证后完整日文地址 | 标准化后的完整地址（含邮编） |
| 验证后邮编 | 验证/修正后邮编 |
| 验证状态 | ✓ VERIFIED / ⚠ UNVERIFIED / ✓ 已修改 |
| 验证精度 | validation_level 值 |

---

## 状态码与错误

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 参数校验失败（详见 `details` 字段） |
| 401 | 缺少 `X-API-Key` 请求头 |
| 403 | API Key 无效或无权限 |
| 429 | 请求频率超限（默认 60 秒内 10000 次） |
| 500 | 服务器内部错误 |

### 400 错误响应示例

```json
{
  "status": "error",
  "message": "Validation failed",
  "details": [
    { "path": "raw_address", "message": "raw_address is required" },
    { "path": "provided_zipcode", "message": "provided_zipcode is required" }
  ]
}
```

### 500 错误响应示例

```json
{
  "status": "error",
  "message": "Address cleansing failed",
  "details": "Google Maps API quota exceeded"
}
```

---

## 地址验证精度说明

| validation_level | verdict_level | 说明 |
|------------------|---------------|------|
| `SUB_PREMISE`    | `reliable` | 精确到房间号，可直接用于寄递 |
| `PREMISE`        | `reliable` | 精确到门牌号，可直接用于寄递 |
| `STREET_ADDRESS` | `trusted`  | 验证到街道级别，基本可用于寄递 |
| `ROUTE`          | `review`   | 仅精确到道路级别，建议核实 |
| `NEIGHBORHOOD`   | `review`   | 仅精确到街区级别，建议核实 |
| `LOCALITY`       | `unreliable` | 仅精确到城市级别，需人工核实 |
| `OTHER`          | `unreliable` | 地址无法精确匹配，需人工核实 |
| `UNKNOWN`        | `unreliable` | 验证失败，需人工核实 |

---

## 清洗流程

单次地址清洗的内部处理流程如下：

1. **提取房间号**：从原始地址中识别并剥离 `号室`、`階`、`F/f` 等房间后缀，保留基础地址
2. **ZipCloud 邮编查询**：调用 [ZipCloud API](http://zipcloud.ibsnet.co.jp/api/search) 校验邮编有效性，获取对应行政区域
3. **Google Maps 地理编码**：使用 Google Geocoding API 对基础地址进行日文 + 英文双向地理编码
4. **Google Address Validation**：调用 Google Address Validation API 获取地址精度等级（granularity）
5. **房间号回填**：将剥离的房间号重新附加到验证后的日文/英文地址
6. **判定生成**：根据精度等级映射 verdict 和中文判定信息
7. **结果缓存**：高质量结果（SUB_PREMISE / PREMISE / STREET_ADDRESS）写入 Redis 缓存

### 处理说明

- 仅当 `raw_address` 包含房间号（如 `501号室`、`3F`、`2階`）时才执行房间号剥离与回填
- 若基础地址验证失败但存在房间号，自动回退尝试完整地址
- Google Maps API Key 不可用时，回退为仅 ZipCloud 邮编验证模式（精度降为 LOCALITY）
- 结果来源标记：`live`（实时查询）/ `cache`（缓存命中）/ `fallback`（降级）

---

## 快速测试

```bash
# 单条地址清洗
curl -X POST http://101.32.239.62:18933/api/v1/jp/cleanse/address \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ch_your_api_key_here" \
  -d '{
    "order_id": "TEST-001",
    "raw_address": "160-0023 东京都新宿区西新宿2-8-1",
    "provided_zipcode": "160-0023"
  }'

# 批量地址清洗
curl -X POST http://101.32.239.62:18933/api/v1/jp/cleanse/address \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ch_your_api_key_here" \
  -d '[
    { "order_id": "SF-001", "raw_address": "160-0023 东京都新宿区西新宿2-8-1", "provided_zipcode": "160-0023" },
    { "order_id": "SF-002", "raw_address": "530-0002 大阪府大阪市北区曽根崎新地1-1-1", "provided_zipcode": "530-0002" }
  ]'

# Excel 上传
curl -X POST http://101.32.239.62:18933/api/v1/jp/cleanse/address/upload \
  -H "X-API-Key: ch_your_api_key_here" \
  -F "file=@addresses.xlsx"
```
