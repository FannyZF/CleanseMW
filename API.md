# Customs API Hub — 客户 API 接口文档

**版本**: 2.0  
**Base URL**: `http://your-server:port/api/v1`

---

## 通用说明

### 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Content-Type` | 是 | `application/json` |
| `X-API-Key` | 是 | 由系统管理员分配的唯一 API 密钥，格式 `ch_xxxx...` |

### 批量请求

所有接口均支持单条和批量两种方式。发送数组 `[{...}, {...}]` 自动识别为批量，上限 100 条。

### 数据完整性

每个响应自动包含 `request_hash` 和 `response_hash`（SHA256 指纹），用于争议时验证数据未被篡改。

### 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数校验失败 |
| 401 | 缺少 `X-API-Key` |
| 403 | Key 无效或无权访问 |
| 429 | 频率超限 |
| 500 | 服务器错误 |

---

# 一、日本线路 (Japan)

## 1. HS 编码分类 (含税金预估)

```
POST /classify          (兼容旧版)
POST /jp/classify       (推荐)
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw_description` | string | 是 | 产品描述（中/英文，建议含品牌、材质、功能） |
| `hs_code` | string | 否 | 验证模式：提供 HS 编码判断是否匹配 |
| `sale_price` | number | 否 | 商品销售价。传入后自动返回关税/消费税预估 |
| `currency` | string | 否 | 销售价币种，默认 `CNY`。支持 `CNY` / `JPY` / `USD` |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"success"` |
| `task_id` | string | 任务唯一标识 |
| `suggested_name` | string | 建议品名 |
| `hs_code` | string\|null | 最匹配的 HS 编码 |
| `description` | string\|null | HS 编码描述 |
| `confidence` | number | 置信度 0~1 |
| `duty` | object\|null | **税金预估（仅传入 `sale_price` 时返回）** |

### duty（日本）字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `duty.rate` | number | 日本 MFN 关税率 |
| `duty.estimated_duty` | number | 预估关税（JPY） |
| `duty.consumption_tax` | number | 预估消费税 10%（JPY） |
| `duty.total_tax` | number | 总税金 = 关税 + 消费税（JPY） |
| `duty.currency` | string | `"JPY"` |
| `duty.source_currency` | string | 用户传的币种 |
| `duty.exchange_rate` | number | 应用的汇率 |
| `duty.note` | string | 免责声明 |

### 示例

**基本分类：**
```json
POST /jp/classify
{ "raw_description": "SHEIN牌女士纯棉上衣" }
```
```json
{
  "status": "success",
  "task_id": "abc123",
  "suggested_name": "女装上衣纯棉",
  "hs_code": "61061000",
  "description": "棉制针织或钩编女衬衫",
  "confidence": 0.85
}
```

**含税金预估：**
```json
POST /jp/classify
{ "raw_description": "SHEIN牌女士纯棉上衣", "sale_price": 2000, "currency": "CNY" }
```
```json
{
  "hs_code": "61061000",
  "confidence": 0.85,
  "duty": {
    "rate": 0.09,
    "estimated_duty": 3690,
    "consumption_tax": 4490,
    "total_tax": 8180,
    "currency": "JPY",
    "source_currency": "CNY",
    "exchange_rate": 20.5,
    "note": "6位HS级估算，仅供参考，实际以日本海关核定为准"
  }
}
```

> 日本税金 = 关税（CIF × MFN 税率）+ 消费税 10% ×（CIF + 关税）。税率基于中国原产货物适用 WTO 最惠国税率。

---

## 2. 地址清洗

```
POST /cleanse/address   (兼容旧版)
POST /jp/cleanse/address (推荐)
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | string | 否 | 订单号，未提供时系统自动生成 |
| `raw_address` | string | 是 | 原始地址（日/英/中） |
| `provided_zipcode` | string | 是 | 邮编 |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `reference_id` | string | 请求唯一标识 |
| `data.address.is_valid` | boolean | 地址是否有效 |
| `data.address.validation_level` | string | 验证精度：`PREMISE` / `STREET_ADDRESS` / `LOCALITY` / `OTHER` |
| `data.address.verdict_level` | string | 寄递建议：`reliable`（可信）/ `trusted`（基本可信）/ `review`（需核实）/ `unreliable`（不可用） |
| `data.address.verdict_message` | string | 中文提示 |
| `data.address.japanese_address` | string | 日文地址 |
| `data.address.english_address` | string | 英文地址 |
| `data.zipcode.match` | boolean | 邮编是否匹配 |
| `data.zipcode.suggested_correct` | string\|null | 建议正确邮编 |

### 示例

```json
POST /jp/cleanse/address
{
  "order_id": "SF-001",
  "raw_address": "160-0023 东京都新宿区西新宿2-8-1",
  "provided_zipcode": "160-0023"
}
```

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
      "japanese_address": "東京都新宿区西新宿2丁目8-1",
      "english_address": "2-8-1 Nishishinjuku, Shinjuku City, Tokyo"
    },
    "zipcode": {
      "match": true,
      "provided": "1600023",
      "suggested_correct": null
    }
  },
  "request_hash": "sha256:...",
  "response_hash": "sha256:..."
}
```

---

## 3. 姓名清洗

```
POST /cleanse/name      (兼容旧版)
POST /jp/cleanse/name   (推荐)
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | string | 否 | 订单号 |
| `raw_name` | string | 是 | 姓名（日语/英文/中文） |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.name.original` | string | 原始输入 |
| `data.name.japanese_katakana` | string | 片假名 |
| `data.name.english_romaji` | string | 罗马字 |

```json
POST /jp/cleanse/name
{ "raw_name": "山田太郎" }
```

```json
{
  "status": "success",
  "reference_id": "ref_abc",
  "data": {
    "name": {
      "original": "山田太郎",
      "japanese_katakana": "ヤマダタロウ",
      "english_romaji": "Yamada Taro"
    }
  }
}
```

---

## 4. 商品清洗

```
POST /cleanse/item      (兼容旧版)
POST /jp/cleanse/item   (推荐)
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | string | 否 | 订单号 |
| `raw_description` | string | 是 | 商品描述 |
| `hs_code` | string | 是 | HS 编码 |
| `declared_value_jpy` | number | 是 | 申报价值（日元），> 0 |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.item.hs_code_valid` | boolean | HS 编码是否有效 |
| `data.item.hs_code_description` | string\|null | HS 编码官方描述 |
| `data.item.value_assessment` | string | 价值评估：`normal` / `commercial_threshold` |
| `data.compliance.passed` | boolean | 合规是否通过 |
| `data.compliance.warnings` | array | 合规警告列表 |

### warnings 元素

| 字段 | 类型 | 说明 |
|------|------|------|
| `level` | string | `passed` / `warning` / `restricted` / `blocked` |
| `check` | string | 检查项名称 |
| `message` | string | 详细说明 |

---

## 5. 合规检查

```
POST /compliance/check      (兼容旧版)
POST /jp/compliance/check   (推荐)
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `items` | array | 是 | 待检查商品列表（1~100个） |

### items 元素

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw_description` | string | 是 | 商品描述 |
| `hs_code` | string | 是 | HS 编码 |
| `declared_value_jpy` | number | 是 | 申报价值（日元） |

### 响应参数

```json
{
  "status": "success",
  "results": [{
    "raw_description": "Cotton T-Shirt",
    "hs_code": "61091000",
    "declared_value_jpy": 3000,
    "compliance": { "passed": true, "warnings": [] }
  }]
}
```

---

# 二、美国线路 (US)

## 1. HTS 编码分类 (含税金预估)

```
POST /us/classify
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw_description` | string | 是 | 产品描述（英文） |
| `hs_code` | string | 否 | 验证模式：提供编码进行匹配验证 |
| `sale_price` | number | 否 | 商品销售价。传入后自动返回关税/税费预估 |
| `currency` | string | 否 | 销售价币种，默认 `CNY`。支持 `CNY` / `JPY` / `USD` |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | string | `"classify"` / `"verify"` |
| `suggested_name` | string | 建议品名 |
| `best_guess` | object\|null | 最佳匹配：`{ hs_code, description, confidence, matched_keywords }` |
| `candidates` | array | 候选编码列表 |
| `extracted_keywords` | array | 提取的关键词 |
| `duty` | object\|null | **税金预估（仅传入 `sale_price` 时返回）** |

### duty（美国）字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `duty.base_rate` | number | 美国 MFN 关税率 |
| `duty.section_301` | number | Section 301 对华惩罚性附加关税 |
| `duty.additional_tariffs` | number | 其他附加关税（IEEPA 等） |
| `duty.total_rate` | number | 总税率 = MFN + 301 + additional |
| `duty.estimated_duty` | number | 预估关税（USD） |
| `duty.mpf` | number | 货物处理费 MPF（USD） |
| `duty.total_tax` | number | 总关税 = estimated_duty（不含 MPF） |
| `duty.mpf` | number | MPF 最低值 $29.66（提示参考） |
| `duty.mpf_note` | string | MPF 收费标准说明 |
| `duty.currency` | string | `"USD"` |
| `duty.source_currency` | string | 用户传的币种 |
| `duty.exchange_rate` | number | 应用的汇率 |
| `duty.note` | string | 免责声明 |

### 示例

**基本分类：**
```json
POST /us/classify
{ "raw_description": "Laptop Computer" }
```
```json
{
  "status": "success",
  "mode": "classify",
  "suggested_name": "Laptop Computer",
  "best_guess": {
    "hs_code": "84713000",
    "description": "Portable automatic data processing machines...",
    "confidence": 0.92,
    "matched_keywords": ["computer", "automatic", "processing"]
  },
  "extracted_keywords": ["laptop", "computer"]
}
```

**含税金预估：**
```json
POST /us/classify
{ "raw_description": "Cotton T-Shirt", "sale_price": 100, "currency": "CNY" }
```
```json
{
  "hs_code": "61091000",
  "confidence": 0.91,
  "duty": {
    "base_rate": 0.12,
    "section_301": 0.15,
    "total_rate": 0.27,
    "estimated_duty": 3.73,
    "mpf": 29.66,
    "mpf_note": "MPF is per customs entry: 0.3464% of entered value, min $29.66, max $575.35 per entry",
    "total_tax": 3.73,
    "currency": "USD",
    "source_currency": "CNY",
    "exchange_rate": 0.138,
    "note": "6位HS级估算，仅供参考，实际以CBP核定为准"
  }
}
```

> 美国税金 = 关税（CIF × (MFN + Section 301)）+ 货物处理费（MPF ≥ $29.66）。税率基于中国原产货物，Section 301 附加税根据 USTR 现行公告。

---

## 2. 地址清洗

```
POST /us/cleanse/address
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_id` | string | 否 | 订单号 |
| `raw_address` | string | 是 | 原始地址 |
| `zipcode` | string | 是 | 邮编 |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"success"` |
| `task_id` | string | 任务唯一标识 |
| `mode` | string | `"classify"` / `"verify"` |
| `suggested_name` | string | 建议品名 |
| `hs_code` | string\|null | 最匹配的 HS/HTS 编码 |
| `description` | string\|null | 编码描述 |
| `confidence` | number | 置信度 0~1 |
| `duty` | object\|null | **税金预估（仅传入 `sale_price` 时返回）** |

验证模式额外字段（传入 `hs_code` 时）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `provided_hs_code` | string | 用户提供的编码 |
| `hs_code_valid` | boolean | 编码是否有效 |
| `suggested_hs_code` | string\|null | 系统建议的编码 |
| `matched` | boolean | 是否匹配 |

### 示例

**基本分类：**
```json
POST /us/classify
{ "raw_description": "Laptop Computer" }
```
```json
{
  "status": "success",
  "task_id": "abc123",
  "mode": "classify",
  "suggested_name": "Laptop Computer",
  "hs_code": "84713000",
  "description": "Portable automatic data processing machines...",
  "confidence": 0.92
}
```

**含税金预估：**
```json
POST /us/classify
{ "raw_description": "Cotton T-Shirt", "sale_price": 100, "currency": "CNY" }
```
```json
{
  "status": "success",
  "task_id": "def456",
  "mode": "classify",
  "suggested_name": "Cotton T-Shirt",
  "hs_code": "61091000",
  "description": "T-shirts, singlets..., of cotton",
  "confidence": 0.91,
  "duty": {
    "base_rate": 0.12,
    "section_301": 0.15,
    "total_rate": 0.27,
    "estimated_duty": 3.73,
    "mpf": 29.66,
    "mpf_note": "MPF is per customs entry: 0.3464% min $29.66 max $575.35 per entry",
    "total_tax": 3.73
  }
}
```

### address_type 判定逻辑

| 来源 | 判定 |
|------|------|
| USPS DPV `"D"` / CMRA `"Y"` | `commercial` |
| USPS DPV `"Y"` / `"S"` | `residential` |
| 文本含 Office/Plaza/LLC 等 | `commercial` |
| 文本含 Apt/Unit/# 等 | `residential` |
| 无法判断 | `unknown` |

> 住宅地址可能涉及快递公司的额外派送费用。

---

## 3. 合规检查

```
POST /us/compliance/check
```

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `items` | array | 是 | 待检查商品列表（1~100个） |

### items 元素

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `raw_description` | string | 是 | 商品描述 |
| `hs_code` | string | 是 | HS/HTS 编码 |
| `declared_value_usd` | number | 是 | 申报价值（美元） |
| `weight_lbs` | number | 否 | 重量（磅） |
| `length_in` | number | 否 | 长（英寸） |
| `width_in` | number | 否 | 宽（英寸） |
| `height_in` | number | 否 | 高（英寸） |
| `address_hint` | string | 否 | 地址提示（用于 PO Box 检测） |

### 响应参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `passed` | boolean | 是否通过 |
| `hs_code_valid` | boolean | HS 编码是否有效 |
| `warnings` | array | 合规警告 |
| `carrier_restrictions` | object\|null | 承运限制：`{ usps, fedex, ups }` |

### 示例

```json
POST /us/compliance/check
{
  "items": [{
    "raw_description": "Lithium Battery Pack",
    "hs_code": "85076000",
    "declared_value_usd": 120,
    "weight_lbs": 5,
    "length_in": 12, "width_in": 8, "height_in": 4
  }]
}
```

```json
{
  "status": "success",
  "results": [{
    "raw_description": "Lithium Battery Pack",
    "hs_code": "85076000",
    "declared_value_usd": 120,
    "passed": true,
    "hs_code_valid": true,
    "warnings": [{
      "level": "restricted",
      "check": "restricted_goods",
      "message": "锂电池：需符合UN38.3检测，限量运输"
    }],
    "carrier_restrictions": null
  }]
}
```

---

## 6. 地址批量上传 (Excel)

```
POST /jp/cleanse/address/upload    (上传并返回审核表格)
POST /jp/cleanse/address/download  (下载修正后的Excel)
```

仅限日本地址。详细格式参见管理后台 `Address Cleanse` 页面上传引导。

---

## 附录

### 日本合规检查项

| 检查项 | 说明 | 状态 |
|--------|------|------|
| `prohibited_goods` | 违禁品（武器、毒品、仿制品） | `blocked` |
| `restricted_goods` | 限制品（锂电池、药品、食品） | `restricted` |
| `commercial_threshold` | 商业件阈值 | `warning` |
| `cn_trademark_risk` | 中国品牌侵权风险 | `warning` |
| `hs_code_mismatch` | HS 编码与描述不匹配 | `warning` |

### 日本地址验证精度

| validation_level | verdict_level | 说明 |
|------------------|---------------|------|
| `PREMISE` | `reliable` | 精确到门牌，可用于寄递 |
| `SUB_PREMISE` | `reliable` | 精确到房间号 |
| `STREET_ADDRESS` | `trusted` | 街道级，基本可用 |
| `ROUTE` | `review` | 需核实 |
| `LOCALITY` | `unreliable` | 精度不足，需核实 |
| `OTHER` | `unreliable` | 无法匹配，需人工确认 |
