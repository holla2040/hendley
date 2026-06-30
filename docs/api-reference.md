# JLCPCB OpenAPI — Reference

This document captures the JLCPCB OpenAPI contract, cross-checked from three
sources: the console **"View Docs" PDFs** (the primary, authoritative source for
request/response shapes — transcribed in full below), the official **Java SDK
jars** (`sdk/`, authoritative for serialized field names), and — for the
component routes and the PCB uploads — the **live API**. It is the source of
truth for the Python reimplementation in `src/hendley/` (`client.py` wraps every
endpoint here).

- **Endpoint (overseas/global):** `https://open.jlcpcb.com` (the default in
  `config.py`; also what every official PDF uses). `api.jlcpcb.com` is the
  developer portal/console, *not* the API host. The Java SDK's baked-in default
  is `https://openapi.jlc.com` (China).
- **All JSON routes are `POST`** (even getter-shaped names); file uploads are
  `POST multipart/form-data`.

## Contents

- [Live-verified deviations from the PDFs](#live-verified-deviations-from-the-pdfs) ⚠️
- [Authentication — the `JOP` scheme](#authentication--the-jop-scheme)
- [Serialization & response envelope](#serialization--response-envelope)
- [Component (parts inventory) endpoints](#component-parts-inventory-endpoints)
  - [`component/getComponentLibraryList` — Get Component list](#post-overseasopenapicomponentgetcomponentlibrarylist--get-component-list)
  - [`component/getComponentDetailByCode` — Query Component Detail Data Interface](#post-overseasopenapicomponentgetcomponentdetailbycode--query-component-detail-data-interface)
  - [`component/getComponentInfos` — Component information interface](#post-overseasopenapicomponentgetcomponentinfos--component-information-interface)
  - [`component/getPrivateComponentLibrary` — Query Private Component Library Interface](#post-overseasopenapicomponentgetprivatecomponentlibrary--query-private-component-library-interface)
- [PCB order endpoints](#pcb-order-endpoints)
  - [`pcb/uploadGerber` — Upload PCB Gerber Files](#post-overseasopenapipcbuploadgerber--upload-pcb-gerber-files)
  - [`pcb/uploadBlindViaHoleImg` — Upload Blind Slot Image](#post-overseasopenapipcbuploadblindviaholeimg--upload-blind-slot-image)
  - [`pcb/getImpedanceTemplateSettingList` — PCB Stack-up Configuration Information](#post-overseasopenapipcbgetimpedancetemplatesettinglist--pcb-stack-up-configuration-information)
  - [`pcb/calculate` — Online Quotation](#post-overseasopenapipcbcalculate--online-quotation)
  - [`pcb/audit/get` — PCB Pre-review Information](#post-overseasopenapipcbauditget--pcb-pre-review-information)
  - [`pcb/order/detail` — Order Information Query API](#post-overseasopenapipcborderdetail--order-information-query-api)
  - [`pcb/wip/get` — PCB Production Progress Query](#post-overseasopenapipcbwipget--pcb-production-progress-query)
  - [`pcb/create` — Create an order](#post-overseasopenapipcbcreate--create-an-order)
  - [`pcb/getSteelPriceConfig` — Steel/Stencil Price Config](#post-overseasopenapipcbgetsteelpriceconfig--steelstencil-price-config)
- [TDP (3D-printing / JLC3DP) order endpoints](#tdp-3d-printing--jlc3dp-order-endpoints)
  - [`tdp/api/upload` — JLC3DP File Upload Interface](#post-overseasopenapitdpapiupload--jlc3dp-file-upload-interface)
  - [`tdp/api/file/result` — JLC3DP File Parsing Result (Polling Interface)](#post-overseasopenapitdpapifileresult--jlc3dp-file-parsing-result-polling-interface)
  - [`tdp/api/calculate` — JLC3DP Calculate Product Price Interface](#post-overseasopenapitdpapicalculate--jlc3dp-calculate-product-price-interface)
  - [`tdp/api/order/create` — JLC3DP Create Order Interface](#post-overseasopenapitdpapiordercreate--jlc3dp-create-order-interface)
  - [`tdp/api/order/list` — JLC3DP Order List Interface](#post-overseasopenapitdpapiorderlist--jlc3dp-order-list-interface)
  - [`tdp/api/order/detail` — JLC3DP Order Details Interface](#post-overseasopenapitdpapiorderdetail--jlc3dp-order-details-interface)
  - [`tdp/api/order/process` — JLC3DP Order Progress Interface](#post-overseasopenapitdpapiorderprocess--jlc3dp-order-progress-interface)

---
## Live-verified deviations from the PDFs

The per-endpoint sections below are faithful transcriptions of the official PDFs.
But several PDF claims are **wrong against the live server** — where they
disagree, the live API wins. Confirmed by real calls:

1. **Private-stock paging is `currentPage`, not the PDF's `pageNum`.** The server
   silently ignores `pageNum` and always returns page 1. (`getPrivateComponentLibrary`)
2. **`data` is a bare list for `getComponentDetailByCode` and
   `getPrivateComponentLibrary`** — not the `componentDetailResponseVOList` /
   `{list, pageNum, total}` wrapper objects the PDFs show.
3. **`getComponentInfos` is a normal JSON `POST` at
   `/overseas/openapi/component/getComponentInfos`** — ignore that PDF's
   `api.jlcpcb.com/demo/component/info` multipart example (stale/demo). Its live
   response is `{componentInfos, lastKey}` and the package field is `package`.
4. **File uploads sign an *empty* payload** (see "File uploads" below), **not**
   the `Content-MD5` scheme the PDFs' `application/json` header note implies.
5. The live `getComponentDetailByCode` row also returns `dataManualUrl`,
   `dataManualOfficialLink`, `dataManualFileAccessId`; the SDK's
   `lcscComponentId` is not returned.

## Authentication — the `JOP` scheme

Each request carries an `Authorization` header built as follows
(`com.jlc.openapi.core.client.auth.authorization.SignAuthorization`):

```
string_to_sign = METHOD + "\n"
               + CANONICAL_URI + "\n"        # raw path, plus "?"+rawQuery if present
               + TIMESTAMP + "\n"            # str(int(epoch_seconds))
               + NONCE + "\n"                # 32-char random token
               + PAYLOAD + "\n"              # exact request body; "" for GET and for uploads

signature = Base64( HMAC_SHA256(secret_key, string_to_sign) )

Authorization: JOP appid="<AppID>",accesskey="<Accesskey>",
               timestamp="<ts>",nonce="<nonce>",signature="<signature>"
```

Defaults from the SDK (`AuthProfile.Builder`): authenticator `JOP` (scheme is
literally `JOP`, no algorithm suffix), sign algorithm `HMAC_SHA256`. The
`secret_key` is the `.keys` `SecretKey`; `accesskey` is the `.keys` `Accesskey`.
Other algorithms exist but are not the default: `HmacSHA1`, `SHA256withRSA`
(`RSA_SHA256`), `HMAC-SM3`.

Standard headers on every JSON call: `Authorization`,
`Content-Type: application/json`, `Accept: application/json`, `Accept-Language`,
`User-Agent`.

### File uploads (signing + transport)

`uploadGerber`, `uploadBlindViaHoleImg`, and the TDP `upload` route are
`POST multipart/form-data` with a `file` part plus a `fileName` form field. They
**sign an empty `PAYLOAD`** (the file is not part of the string-to-sign) —
verified live (an MD5/`Content-MD5` payload returns `401 signature verify
failed`). The PDFs' `Content-Type: application/json` header note is boilerplate
and wrong for these routes. The PCB uploads return the file id in `data`; the TDP
upload returns it in `message`.

### Field tokenization (privacy) — orders only

For order placement the SDK can RSA-encrypt sensitive address fields with the
public key in `.keys` ("Tokenization Key RSA"). Algorithm is RSA (PKCS#1 v1.5) or
SM2. **Not needed for read-only parts queries**; `client.py` does not implement
it, so order-placement addresses are currently sent unencrypted.

## Serialization & response envelope

`toJSON()` serializes Java fields by their **camelCase names**; **null fields are
omitted** (mirrored by `client._post`). Responses wrap payloads as
`{ code, message, data }` with success code `200`, but the success flag and
message keys vary by service:

- success flag: `success` (component/PCB) **or** `successful` (TDP `upload`)
- message key: `message` (most) **or** `msg` (some TDP routes)
- the file id on TDP `upload` is in `message`, not `data`

`client._success` / `_unwrap` / `_check` normalize all of these. Component error
envelopes use HTTP-style codes (200/401/403/429/4XX/500); PCB order routes use a
numeric business-code table (1000–5006, reproduced under `calculate`).

---

# Endpoints

Each PDF-backed section gives the request parameter table, nested-object tables,
full response schema, error codes, and the PDF's example (`getSteelPriceConfig`
is the exception — it has no PDF and is jar-only). The matching `client.py`
method is named in a **Hendley** line under each heading.

## Component (parts inventory) endpoints
### `POST /overseas/openapi/component/getComponentLibraryList` — Get Component list

**Hendley:** `JLCClient.get_component_library_list() / iter_component_library()`

Paginated query for the listed component data, supporting large-volume data pagination.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| pageSize | Integer | Yes | Page size, the default value is 30 |
| lastKey | String | No | The last item on the current page serves as the key to retrieve the next page's data |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| componentLibraryInfoVOS | Object[] | List of component library entries |
| lastKey | String | The last item on the current page, used as the key to retrieve the next page's data |

**`componentLibraryInfoVOS[]`**

| Field | Type | Description |
|---|---|---|
| componentModel | String | Component model |
| componentCode | String | Component code (C code) |
| componentSpecification | String | Component package/specification |

> Note: The top-level envelope in the example uses `successful` (not `success`) and includes `code`, `data`, `message`.

**Errors**

| Code | Meaning |
|---|---|
| 200 | success |
| 401 | unauthorized |
| 403 | forbidden |
| 429 | too many requests |
| 4XX | param error |
| 500 | inner server error |

**Example**

Request:
```json
{
  "pageSize": 100,
  "lastKey": "UbYoSFARDyd74EPOb5BYUPu+tjNN8513mTE1nW/GDH3OPh8lgrrENTIeTt44+S/O8WE/U0J1iUmfex3m5mvWPRvKSu9Fmt2jscj0cwia/spvy/7YgSbpJiYp1tFMNLc6FLb1UYAgxxP4xoDxvQ8gYhegLQKcWt6PKVqYesLUPE="
}
```
Response:
```json
{
  "code": 200,
  "data": {
    "componentLibraryInfoVOS": [
      {
        "componentModel": "GZ1608D601TF",
        "componentCode": "C1002",
        "componentSpecification": "0603"
      },
      {
        "componentModel": "GZ1608D151TF",
        "componentCode": "C1003",
        "componentSpecification": "0603"
      }
    ],
    "lastKey": "ToGZ62vgp+l12fVWfRXu032retQPX9P1I4ha3j1HGqFz8XXSR9GCI6pj75fSZbkdIwYDaPuJ2CNxbvK2TU+QZI0+LkzPHTR0kfVaR+WnrnPtobj6RaffNgeRVJgEBEiHViPRTpxAd+uki3kiRSM336qtcMwfIJDLEdcSxiSs7j8="
  },
  "message": null,
  "successful": true
}
```

---

### `POST /overseas/openapi/component/getComponentDetailByCode` — Query Component Detail Data Interface

**Hendley:** `JLCClient.get_component_detail_by_code(codes)`

Query Component Details by C Code.

> ⚠ **Live deviation** (see [Live-verified deviations](#live-verified-deviations-from-the-pdfs)): the live response `data` is the **bare list** of detail objects — the `componentDetailResponseVOList` wrapper shown below is not what the server sends. Live rows also include `dataManualUrl`/`dataManualOfficialLink`/`dataManualFileAccessId` and omit `lcscComponentId`.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| componentCodes | String[] | Yes | An array of component codes for batch querying. Supports up to 1000 component codes. |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| componentDetailResponseVOList | Object[] | List of component detail entries |

**`componentDetailResponseVOList[]`**

| Field | Type | Description |
|---|---|---|
| componentCode | String | Code |
| componentModel | String | model |
| componentSpecification | String | Component Package |
| firstTypeName | String | First Type |
| secondTypeName | String | Second Type |
| libraryType | String | Library Type |
| description | String | Description |
| datasheetUrl | String | Data sheet file ID |
| solderJointCount | Integer | Number of solder joints |
| priceRanges | Object[] | Price ranges |
| stockCount | Integer | stock quantity |
| parameters | Object[] | parameter |
| eccnCode | String | ECCN code |
| rohsFlag | Boolean | Rohs |
| assemblyComponentFlag | Boolean | Is Fabricated Component? |

**`priceRanges[]`**

| Field | Type | Description |
|---|---|---|
| startQuantity | Integer | Starting quantity |
| endQuantity | Integer | End Quantity |
| unitPrice | Number | price |

**`parameters[]`**

| Field | Type | Description |
|---|---|---|
| parameterName | String | Parameter name |
| parameterValue | String | Parameter value |

**Errors**

| Code | Meaning |
|---|---|
| 200 | success |
| 401 | unauthorized |
| 403 | forbidden |
| 429 | too many requests |
| 4XX | param error |
| 500 | inner server error |

**Example**

Request:
```json
{
  "componentCodes": ["C8734", "C82899"]
}
```
Response:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "componentDetailResponseVOList": [
      {
        "componentCode": "C8734",
        "componentModel": "STM32F103C8T6",
        "componentSpecification": "LQFP-48",
        "firstTypeName": "Microcontrollers",
        "secondTypeName": "ARM Microcontrollers",
        "libraryType": "Basic",
        "description": "ARM Cortex-M3 MCU, 72MHz, 64KB Flash, 20KB RAM",
        "datasheetUrl": "https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
        "solderJointCount": 48,
        "priceRanges": [
          { "startQuantity": 1, "endQuantity": 9, "unitPrice": 1.5000 },
          { "startQuantity": 10, "endQuantity": 99, "unitPrice": 1.2500 },
          { "startQuantity": 100, "endQuantity": 999, "unitPrice": 1.0000 }
        ],
        "stockCount": 10000,
        "parameters": [
          { "parameterName": "Core", "parameterValue": "ARM Cortex-M3" },
          { "parameterName": "Flash Size", "parameterValue": "64KB" },
          { "parameterName": "RAM Size", "parameterValue": "20KB" },
          { "parameterName": "Operating Voltage", "parameterValue": "2.0V ~ 3.6V" }
        ],
        "assemblyComponentFlag": true,
        "eccnCode": "3A991.a.2",
        "rohsFlag": true
      }
      // … more entries (C82899 ESP32-WROOM-32, C15663 1N4007) …
    ]
  }
}
```

---

### `POST /overseas/openapi/component/getComponentInfos` — Component information interface

**Hendley:** `JLCClient.get_component_infos() / iter_component_infos()`

Component information interface — paginated list of component information (LCSC parts catalog).

> Note: This PDF (titled "JLCPCB Component API — 1. Component information interface") documents a **different host and path** than the other three: `Request URL : https://api.jlcpcb.com/demo/component/info`. It is also the only endpoint shown as a **multipart/form-data** request (`MultipartBody.FORM`, `text/plain`) rather than a JSON body. The task assigns this the canonical name `getComponentInfos` on the `open.jlcpcb.com/overseas/openapi/component/` host; the section header reflects that canonical path while this note records the PDF's literal `api.jlcpcb.com/demo/component/info`.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| lastKey | body form | no | The last item on the current page can be used as a key to access the next page of data |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| componentInfos | Object[] | A list of component information. |
| lastKey | String | The last row of the current page can be used as a key to get information of the next page. |

**`componentInfos[]`**

| Field | Type | Description |
|---|---|---|
| lcscPart | String | LCSC part / C code |
| firstCategory | String | First category |
| secondCategory | String | Second category |
| mfrPart | String | Manufacturer part / package designators |
| solderJoint | String | Number of solder joints |
| manufacturer | String | Manufacturer |
| libraryType | String | Library type (e.g. `expand`) |
| description | String | Description |
| datasheet | String | Datasheet URL |
| price | String | Price tiers, encoded as `qtyRange:unitPrice` pairs joined by commas |
| stock | Integer | Stock quantity |
| package | String | Package |

**Errors**

| Code | Meaning |
|---|---|
| 200 | success |
| 401 | unauthorized |
| 403 | forbidden |
| 429 | too many requests |
| 4XX | param error |
| 500 | inner server error |

**Example**

Request (multipart form field `lastKey`, converted to its JSON-equivalent payload):
```json
{
  "lastKey": "UbYoSFARDyd74EPOb5BYUPu+tjNN8513mTE1nW/GDH3OPh8lgrrENTIeTt44+S/O8WE/U0J1iUmfex3m5mvWPRvKSu9Fmt2jscj0cwia/spvy/7YgSbpJiYp1tFMNLc6FLGb1UYAgxxP4xoDxvQ8gYhegLQKcWt6PKVqYesLUPE="
}
```
Response:
```json
{
  "success": true,
  "code": 200,
  "message": null,
  "data": {
    "componentInfos": [
      {
        "lcscPart": "C2727",
        "firstCategory": "Diodes",
        "secondCategory": "Schottky Barrier Diodes (SBD)",
        "mfrPart": "TO-220,TO-220-3",
        "solderJoint": "3",
        "manufacturer": "ON Semiconductor",
        "libraryType": "expand",
        "description": "200V 10A 900mV @ 10A TO-220(TO-220-3) Schottky Barrier Diodes (SBD) ROHS",
        "datasheet": "https://datasheet.lcsc.com/lcsc/1809221022_ON-Semiconductor-MBR20200CTG_C2727.pdf",
        "price": "1-9:0.804724409,10-29:0.585826772,30-99:0.544881890,100-499:0.505511811,500-999:0.486614173,1000-:0.478740157,2000-3999:0.470866142,4000-:0.467716535",
        "stock": 217,
        "package": "0603"
      }
    ],
    "lastKey": "POFTQ8ZidxVrP1bNKADY80hiNnK4LUrXsnCAZihLIlXjgxN82D2pEWBY8K/7Rp1bi2H6zIOKa7gzQk+W+1MEunqbcvHM/bPikGWL0gatuhexnajjc9wCUmegogNbOCr2Cbg+dTGOFb8pVFjVQZn7MDRoJlHDWiAXbKdFikibNB8="
  }
}
```

---

### `POST /overseas/openapi/component/getPrivateComponentLibrary` — Query Private Component Library Interface

**Hendley:** `JLCClient.get_private_component_library() / iter_private_component_library()`

Query the private component library of authenticated customers.

> ⚠ **Live deviation** (see [Live-verified deviations](#live-verified-deviations-from-the-pdfs)): paginate with **`currentPage`**, not the PDF's `pageNum` (the server ignores `pageNum` and always returns page 1). The live response `data` is the **bare list** of rows below — not the `{list, pageNum, pageSize, total}` wrapper the PDF shows.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| pageNum | Integer | Yes | Page number, starting from 1, default is 1 |
| pageSize | Integer | Yes | Page size, default is 100 |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| list | Object[] | List of private-library component entries |
| pageNum | Integer | Current page |
| pageSize | Integer | Page size |
| total | Integer | Total records |

**`list[]`**

| Field | Type | Description |
|---|---|---|
| componentModel | String | Model |
| componentSpecification | String | Package |
| componentCode | String | cCode |
| jlcpcbParts | Integer | JLCPCB Parts |
| globalSourcingParts | Integer | Global Sourcing Parts |
| consignedParts | Integer | Consigned Parts |
| idleStock | Integer | Idle Stock |

**Errors**

| Code | Meaning |
|---|---|
| 200 | success |
| 401 | unauthorized |
| 403 | forbidden |
| 429 | too many requests |
| 4XX | param error |
| 500 | inner server error |

**Example**

Request:
```json
{
  "pageNum": 1,
  "pageSize": 100
}
```
Response:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "list": [
      {
        "componentModel": "STM32F103C8T6",
        "componentSpecification": "LQFP-48",
        "componentCode": "C8734",
        "jlcpcbParts": 1000,
        "globalSourcingParts": 500,
        "consignedParts": 200,
        "idleStock": 50
      },
      {
        "componentModel": "ESP32-WROOM-32",
        "componentSpecification": "SMD-38",
        "componentCode": "C82899",
        "jlcpcbParts": 800,
        "globalSourcingParts": 300,
        "consignedParts": 100,
        "idleStock": 25
      }
    ],
    "pageNum": 1,
    "pageSize": 100,
    "total": 1500
  }
}
```

---

## PCB order endpoints

Reverse-engineered from the SDK jars + console PDFs. The two uploads are
live-verified; the JSON order routes reuse the same signed `_post` plumbing
(proven by the component routes) but are **not exercised here** (they price/place
real orders). The large order bodies are passed through `client.py` as dicts
mirroring the JSON below.

# JLCPCB PCB OpenAPI Reference (overseas)

All endpoints are `POST` to host `https://open.jlcpcb.com`. Every request
requires the headers `Authorization` (JOP signature), `Content-Type:
application/json`, and `Accept: application/json`.

> Note on file uploads: the two upload endpoints (`uploadGerber`,
> `uploadBlindViaHoleImg`) take a binary `file` plus an optional `fileName`.
> Although the PDFs show a JSON-shaped example `{"file": , "fileName": "..."}`,
> the actual transfer is a `multipart/form-data` body — the `file` field
> carries the raw file bytes; `fileName` is a form text field. The returned
> string identifier (`data`) is later passed to `calculate`/`create` as
> `fileKey` (Gerber) or to a blind-via `fileInfoList.fileStoreId` (image).

---

### `POST /overseas/openapi/pcb/uploadGerber` — Upload PCB Gerber Files

**Hendley:** `JLCClient.upload_gerber(file)`

Upload a Gerber archive and receive a Gerber file identifier for use as `fileKey`.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| fileName | string | no | Gerber File name |
| file | File | yes | File (rar or zip format) |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| data | string | Gerber File Identifier |

**Errors**

| Code | Meaning |
|---|---|
| 200 | Request Success |
| 2002 | File size exceeds limit |
| 2001 | File verification error |

**Example**

Request:
```json
{
  "fileName": "xxxxx.rar",
  "file":
}
```
> Note: file uploads are multipart/form-data; see the upload note in the reference header.

Response:
```json
{
  "code": 200,
  "message": null,
  "data": "uydgwydgwydgshcjasbdjk"
}
```

---

### `POST /overseas/openapi/pcb/uploadBlindViaHoleImg` — Upload Blind Slot Image

**Hendley:** `JLCClient.upload_blind_via_hole_img(file)`

Upload a blind-via/blind-slot image (PNG/JPG) and receive a file identifier.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| file | File | yes | File (currently supports PNG and JPG, maximum size 10M) |
| fileName | string | no | File name |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| data | string | File Identifier |

**Errors**

| Code | Meaning |
|---|---|
| 200 | Request Success |
| 2006 | File is empty |
| 2001 | File format not supported |
| 2002 | File size exceeds limit |
| 2007 | File upload failed |
| 2008 | File contains risk control content |
| 1003 | System error |

**Example**

Request:
```json
{
  "file": ,
  "fileName": "xxxx.png"
}
```
> Note: file uploads are multipart/form-data; see the upload note in the reference header.

Response:
```json
{
  "code": 200,
  "data": "7286342784632784748",
  "message": null
}
```

---

### `POST /overseas/openapi/pcb/getImpedanceTemplateSettingList` — PCB Stack-up Configuration Information

**Hendley:** `JLCClient.get_impedance_template_setting_list(...)`

Return the matching impedance (stack-up) template list for a given board spec;
the returned `impedanceTemplateCode` feeds `calculate`/`create`.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| stencilLayer | Integer | yes | Board Layer |
| stencilPly | Number | yes | Board Thickness |
| cuprumThickness | Number | yes | Outer copper thickness |
| insideCuprumThickness | Number | yes | Inner copper thickness |
| plateType | Integer | yes | Base material: 1 (FR4), 2 (Aluminum), 4 (Copper Core), 5 (Rogers), 6 (PTFE Teflon), 7 (Flex) |
| delamination | boolean | no | Is layered? |

> Note: the PDF's Body Parameters table labels the inner-copper field as
> "Inside Cuprum Thickness" but the JSON example uses the key
> `insideCuprumThickness`.

**Response `data`** (array of templates)

| Field | Type | Description |
|---|---|---|
| templateName | string | Template Name |
| stencilLayer | int | Board Layer |
| stencilPly | number | Board Thickness |
| cuprumThickness | number | Inner copper thickness |
| insideCuprumThickness | number | Outer copper thickness |
| expeditedFlag | boolean | Is expedited? |
| enableFlag | boolean | Is enabled? |
| impedanceTemplateCode | string | Template Number |
| iaminationList | List | Lamination Structure |
| iaminationList.iaminationType | int | Lamination Structure Type (1, Circuit; 2, PP; 3, Core) |
| iaminationList.content | string | Lamination Structure Content |

> Note (PDF oddity): the response table swaps the copper descriptions versus the
> request — `cuprumThickness` is described as "Inner copper thickness" and
> `insideCuprumThickness` as "Outer copper thickness" (the reverse of the request
> table). The lamination list field/key is literally spelled `iaminationList`
> (and `iaminationType`), and the "expedited" field type is misspelled `boolran`
> in the PDF.

**Errors**

| Code | Meaning |
|---|---|
| 200 | Request Success |
| 3 | Parameter Error |
| 1003 | System Error |

**Example**

Request:
```json
{
  "stencilLayer": 2,
  "stencilPly": 1.6,
  "cuprumThickness": 0.5,
  "insideCuprumThickness": 0.5,
  "plateType": 1,
  "delamination": false
}
```
Response:
```json
{
  "code": 200,
  "message": null,
  "data": [
    {
      "templateName": "xxxxx",
      "stencilLayer": 2,
      "stencilPly": 1.6,
      "cuprumThickness": 0.5,
      "insideCuprumThickness": 0.5,
      "expeditedFlag": true,
      "enableFlag": true,
      "impedanceTemplateCode": "20250125625",
      "iaminationList": [
        { "iaminationType": 1, "content": "" },
        { "iaminationType": 2, "content": "" }
      ]
    }
  ]
}
```

---

### `POST /overseas/openapi/pcb/calculate` — Online Quotation

**Hendley:** `JLCClient.calculate_pcb_price(...)`

Calculate the price (PCB and/or stencil) for an uploaded Gerber and selected craft parameters.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| orderType | Integer | yes | Price Calculation Type: 1 (PCB), 2 (PCB + Stencil), 3 (Stencil) |
| pcbParam | PcbOrderCraftData | no | PCB parameter |
| smtStencilParam | SteelOrderCraftData | no | Stencil parameter |
| achieveDate | Int | yes | Lead Time |
| country | string | no | Country. For value passing, refer to the country code table below, e.g. NL. |
| postCode | string | no | Postal code |
| city | string | no | City |
| fileKey | string | yes | Gerber File Identifier (ID) |
| batchNum | string | no | Batch number |
| shippingMethod | string | no | Shipping Method |

**`pcbParam` — PcbOrderCraftData**

| Field | Type | Required | Description |
|---|---|---|---|
| layer | Integer | yes | PCB Layer |
| width | Number | yes | PCB width (mm) |
| length | Number | yes | PCB length (mm) |
| qty | int | yes | Quantity |
| thickness | Number | yes | PCB thickness |
| pcbColor | Int | yes | Solder mask color: 0-green, 1-red, 2-yellow, 3-blue, 4-White, 5-black, 6-Purple |
| surfaceFinish | Int | yes | Surface finish: 0 – HASL with lead, 1 – Lead-free HASL, 2 – ENIG |
| copperWeight | Number | yes | Outer layer copper weight (oz) |
| insideCuprumThickness | string | yes | Inner layer copper thickness (PDF labels field "Inside Cuprum Thickness") |
| goldFinger | Int | yes | Gold fingers: 0 – Not required, 1 – Required, 2 – Required with bevel edge |
| materialDetails | Int | yes | Material type: 0 – FR4 Standard Tg 140°C |
| panelFlag | int | yes | Is the number of panels customized? 1- Panel by JLCPCB, 0- Single PCB, 2- Panel by Customer |
| panelByJLCPCB_X | Int | yes | Panel count on X axis (required if Panel by JLCPCB or Panel by Customer) |
| panelByJLCPCB_Y | Int | yes | Panel count on Y axis (required if Panel by JLCPCB or Panel by Customer) |
| differentDesign | Int | yes | Number of different designs per panel (Single PCB or Panel by JLCPCB, default value is 1) |
| flyingProbeTest | Int | yes | Flying probe test type: 0 – No test, 1 – Sample test, 2 – 100% test, 6 – Fixture test |
| castellatedHoles | Int | yes | Half hole number: 0, 1, 2, 3, 4 |
| orderDetailsRemark | String | yes | Order detailed remarks |
| cascadeStructure | Int | yes | Stack-up structure type: 0, 1, 2 |
| impedanceTemplateCode | String | no | Impedance Template Code — obtain from getImpedanceTemplateSettingList. Retrieve the corresponding [impedanceTemplateCode] based on: PCB layer, PCB thickness, inner copper thickness, outer copper thickness and base material. |
| impedanceFlag | String | yes | Is impedance required? yes / no |
| isAddCustomerCode | String | yes | Add customer code on board? yes – Add at specified location; Yes – no location specified; nocode – Do not add code |
| plateType | Int | yes | Base material type: 1-FR-4, 2-Aluminum, 4-Copper Core, 5-Rogers, 6-PTFE Teflon, 7-Flex (FPC) |
| autoConfirmProductionFile | Boolean | yes | Is the production file automatically confirmed? |
| markOnPcb | Int | yes | Add Mark on PCB? 1 – No marking, 2 – Add customer code (no location specified), 3 – Add customer code (at specified location), 4 – Add Serial number QR code |
| viaCovering | Int | yes | Via covering type: 1 – Tented, 2 – Untented, 3 – Plugged, 4 – Epoxy Filled&Capped, 5 – Copper paste filled&Capped |
| needTechnics | Int | yes | Need Technics (edge Processing)? 0 – No, 1 – Two sides, 2 – Four sides, 3 – Top and bottom, 4 – Left and right. Single PCB or Panel by Customer, default value is 0 |
| technicsSize | Int | no | Technics Size (mm) — Required when needTechnics is 1, 2, 3, or 4; Single PCB or Panel by Customer, default value is 0 |
| goldThickness | Number | no | ENIG Thickness — Required when surfaceFinish is 2 |
| edgeRounding | Boolean | yes | Is edge rounding required? |
| rowSpacing | Number | no | Row spacing (mm) |
| columnSpacing | Number | no | Column spacing (mm) |
| serviceConfigVos | List<PcbOrderServiceCraftData> | yes | Advanced customization information |
| pcbBlindViaHoleInfoDTOList | List<PcbBlindViaHoleData> | no | Blind Slot Information — Required when serviceConfigVos contains [serviceConfigCode=BVH, serviceConfigShow=Blind Slots, configOptionShow=Yes] |
| edaSoftware | String | no | Design Software — Acceptable values: [Other, EasyEDAPro]. Only used when selecting Flex(FPC) base material; if blank, default is Other. If EasyEDAPro is selected, the Gerber file must be designed with EasyEDA (Pro Edition) |
| fpcGoldFingerThickness | Number | no | Flex(FPC) gold finger thickness; only used with Flex(FPC) base material. When serviceConfigVos contains [serviceConfigCode=GF_CT, serviceConfigShow=Gold Fingers, configOptionShow=Yes], value must be 0.1–1 (mm). Otherwise default 0 |
| serialQrCodeConfigData | SerialQrCodeConfigData | no | QR Code Related Parameters |

**`serialQrCodeConfigData` — SerialQrCodeConfigData**

| Field | Type | Required | Description |
|---|---|---|---|
| qrCodeFormat | Integer | no | QR code formats: 1-QR, 2-DM |
| qrLocation | Integer | no | QR code location: 1 - No requirement, 2 - Specify Position |
| prefixCode | string | no | Prefix Code. Printed QR Code + Plain Code / QR Code Only: 5*5 size supports up to 19 chars; 8*8 up to 34; 10*10 up to 69. Plain Code Only: up to 7 chars |
| addUniqueCode | Boolean | no | Add a unique code? |
| incrCode | String | no | Incremental Code. Printed QR Code + Plain Code / QR Code Only: up to 6 chars. Plain Code Only: up to 7 chars |

**`serviceConfigVos[]` — PcbOrderServiceCraftData**

| Field | Type | Required | Description |
|---|---|---|---|
| serviceConfigCode | string | yes | Customization configuration code |
| serviceConfigShow | string | yes | Display name of the customization configuration |
| configOptionShow | string | yes | Display name of the selected customization option |

**`pcbBlindViaHoleInfoDTOList[]` — PcbBlindViaHoleData**

| Field | Type | Required | Description |
|---|---|---|---|
| idnex | int | yes | Blind slot index (e.g., 1, 2, 3) (PDF spelling: `idnex`) |
| holeAttribute | Int | yes | Hole attribute: 1 – Non-plated (no copper), 2 – Plated (with copper) |
| layerLevel | Int | yes | Layer position: 1 – Top layer, 2 – Bottom layer |
| holeDepth | Number | yes | Hole depth |
| customerRemark | String | yes | Customer remarks |
| fileInfoList | FileData | yes | File information |

**`fileInfoList` — FileData**

| Field | Type | Required | Description |
|---|---|---|---|
| fileStoreId | String | yes | Blind slot image identifier |
| fileName | String | yes | File name |

**`smtStencilParam` — SteelOrderCraftData**

| Field | Type | Required | Description |
|---|---|---|---|
| dimensionsID | Int | yes | Stencil pricing ID |
| stencilQty | int | yes | Stencil Quantity |
| Electropolishing | int | yes | Electropolishing option: 0: No |
| fiducials | int | yes | Fiducial mark type: 0: No Fiducial, 1: Etched Through, 2: Etched Half into board |
| steelPurpose | String | yes | Stencil Process Type: solder_paste – Solder Paste, red_glue – Red Glue |
| customizeFlag | int | yes | Is Stencil dimension customized? 1: customize size, 0: don't customize |
| customizeSizeX | int | no | Custom width (X axis, in mm) |
| customizeSizeY | int | no | Custom height (Y axis, in mm) |
| stencilSide | int | yes | Stencil sides: 0: Top + Bottom (on single stencil), 1: Top only, 2: Bottom only, 3: Top & Bottom (on separate stencils) |
| orderRemark | string | no | Add remarks for stencil order |
| confirmFile | boolean | yes | Is production file confirmed? |
| autoConfirmProductionFile | int | no | Is production file automatically confirmed? 1: Yes, 0: No |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| orderTotalWeight | Number | Order total weight (g) |
| priceWithoutFreight | Number | Cost excluding shipping fees |
| pcbCostInfo | PcbCostInfo | PCB cost information |
| originPcbCostInfo | PcbCostInfo | Original PCB cost information |
| smtStencilCostInfo | SteelCostInfo | Stencil Cost Information |
| shipList | List<ShipInfo> | Shipping methods list |
| achieveDateList | List<AchieveDateInfo> | Lead time list |
| serviceConfigInfoList | List<ServiceConfigInfoList> | Customized option list |
| serviceConfigFeeInfo | List<ServiceConfigFeeInfo> | Customized cost information |
| gerberTop | string | File parsing result top-layer diagram |
| gerberBottom | string | File parsing result bottom-layer diagram |

**`pcbCostInfo` / `originPcbCostInfo` — PcbCostInfo**

| Field | Type | Description |
|---|---|---|
| weight | Number | Weight (g) |
| totalFee | Number | Total cost |
| projectFee | Number | Engineering Fee |
| spellFee | Number | Panelization fee |
| adornPutFee | Number | Spraying fee |
| stencilFee | Number | Board Fee |
| testsFee | Number | Testing Fee |
| fillFee | Number | Film Fee |
| achieveFee | Number | Expedited Fee |
| charFontColor | Number | Color Fee |
| halfHoleFee | Number | Half-hole fee |
| bigBoardFee | Number | Large board fee |
| cuprumThicknessFee | Number | Outer copper thickness fee |
| insideCuprumThicknessFee | Number | Inner copper thickness fee |
| rimCutFee | Number | V-cut fee |
| specialProcessMoney | Number | Special process fee |
| noCodeMoney | Number | Fee for no customer code on the board |
| stackupMoney | Number | Stack-up fee |
| viaCoveringMoney | Number | Solder mask covering fee |
| goldThicknessMoney | Number | Gold plating thickness fee |
| edgeGrindingMoney | Number | Edge grinding fee |
| dummyMoney | Number | Merchandise fee |
| specialMoney | Number | Special offer fee |
| specialFlag | Boolean | Is it a special offer? |
| originStencilMoney | Number | Original board fee |

> Note: the PDF spells the type as `Nmber` throughout PcbCostInfo/SteelCostInfo;
> the JSON example uses `stencilFee` (the field is labeled "Board Fee" /
> "stencil fee").

**`smtStencilCostInfo` — SteelCostInfo**

| Field | Type | Description |
|---|---|---|
| weight | Number | Weight (g) |
| totalFee | Number | Total cost |

**`shipList[]` — ShipInfo**

| Field | Type | Description |
|---|---|---|
| options | String | Shipping method |
| showOptions | String | Shipping method details |
| cost | Number | Cost |
| day | Int | Day |

**`achieveDateList[]` — AchieveDateInfo**

| Field | Type | Description |
|---|---|---|
| achieveName | String | Build time |
| achieveDate | String | Build time (hour) |
| achieveChecked | String | Is it selected? Checked-selected |
| achievePrice | Number | Cost |

**`serviceConfigInfoList[]` — ServiceConfigInfoList**

| Field | Type | Description |
|---|---|---|
| serviceConfigCode | String | Total weight (g) (per PDF; field is the customization code) |
| serviceConfigShow | String | display name of customization |
| configOptionInfoList | List<ConfigOptionInfo> | List of option |

**`configOptionInfoList[]` — ConfigOptionInfo**

| Field | Type | Description |
|---|---|---|
| configOptionShow | String | Display name of option |
| defaultOption | Boolean | Is it the default option? |

**`serviceConfigFeeInfo[]` — ServiceConfigFeeInfo**

| Field | Type | Description |
|---|---|---|
| serviceConfigCode | string | Customized code |
| serviceConfigShow | string | Customized name |
| serviceFee | Number | Cost |
| configOptionName | string | Customized option Name |
| configOptionShow | string | Display name of customized options |

**`country` code table** (full reproduction; PDF columns `名称` = country name,
`国家编码` = country code. Pass the code in the `country` field, e.g. `NL`.)

| Country | Code | Country | Code |
|---|---|---|---|
| AFGHANISTAN | AF | ALBANIA | AL |
| ALGERIA | DZ | AMERICAN SAMOA | AS |
| ANDORRA | AD | ANGOLA | AO |
| ANGUILLA | AI | ANTIGUA | AG |
| ARGENTINA | AR | ARMENIA | AM |
| ARUBA | AW | AUSTRALIA | AU |
| AUSTRIA | AT | AZERBAIJAN | AZ |
| BAHAMAS | BS | BAHRAIN | BH |
| BANGLADESH | BD | BARBADOS | BB |
| BELARUS | BY | BELGIUM | BE |
| BELIZE | BZ | BENIN | BJ |
| BERMUDA | BM | BHUTAN | BT |
| BOLIVIA | BO | BONAIRE | XB |
| BOSNIA AND HERZEGOVINA | BA | BOTSWANA | BW |
| BRAZIL | BR | BRUNEI | BN |
| BULGARIA | BG | BURKINA FASO | BF |
| BURUNDI | BI | CAMBODIA | KH |
| CAMEROON | CM | CANADA | CA |
| CANARY ISLANDS, THE | IC | CAPE VERDE | CV |
| CAYMAN ISLANDS | KY | CENTRAL AFRICAN REPUBLIC | CF |
| CHAD | TD | CHILE | CL |
| COLOMBIA | CO | Commonwealth No. Mariana Islands | MP |
| COMOROS | KM | THE REPUBLIC OF THE CONGO | CG |
| CONGO, THE DEMOCRATIC REPUBLIC OF | CD | COOK ISLANDS | CK |
| COSTA RICA | CR | COTE D IVOIRE | CI |
| CROATIA | HR | CUBA | CU |
| CURACAO | XC | CYPRUS | CY |
| CZECH REPUBLIC, THE | CZ | DENMARK | DK |
| DJIBOUTI | DJ | DOMINICA | DM |
| DOMINICAN REPUBLIC | DO | EAST TIMOR | TL |
| ECUADOR | EC | EGYPT | EG |
| EL SALVADOR | SV | ERITREA | ER |
| ESTONIA | EE | ETHIOPIA | ET |
| FALKLAND ISLANDS | FK | FAROE ISLANDS | FO |
| FIJI | FJ | FINLAND | FI |
| FRANCE | FR | FRENCH GUYANA | GF |
| GABON | GA | GAMBIA | GM |
| GEORGIA | GE | GERMANY | DE |
| GHANA | GH | GIBRALTAR | GI |
| GREECE | GR | GREENLAND | GL |
| GRENADA | GD | GUADELOUPE | GP |
| GUAM | GU | GUATEMALA | GT |
| GUERNSEY | GG | GUINEA REPUBLIC | GN |
| GUINEA-BISSAU | GW | GUINEA-EQUATORIAL | GQ |
| GUYANA (BRITISH) | GY | HAITI | HT |
| HONDURAS | HN | HONG KONG, CHINA | HK |
| HUNGARY | HU | ICELAND | IS |
| INDIA | IN | INDONESIA | ID |
| IRAN (ISLAMIC REPUBLIC OF) | IR | IRAQ | IQ |
| IRELAND, REPUBLIC OF | IE | ISRAEL | IL |
| ITALY | IT | JAMAICA | JM |
| JAPAN | JP | JERSEY | JE |
| JORDAN | JO | KAZAKHSTAN | KZ |
| KENYA | KE | KIRIBATI | KI |
| KOREA, REPUBLIC OF (SOUTH K.) | KR | KOREA, THE D.P.R OF (NORTH K.) | KP |
| KOSOVO | KV | KUWAIT | KW |
| KYRGYZSTAN | KG | LAO PEOPLES DEMOCRATIC REPUBLIC | LA |
| LATVIA | LV | LEBANON | LB |
| LESOTHO | LS | LIBERIA | LR |
| LIBYA | LY | LIECHTENSTEIN | LI |
| LITHUANIA | LT | LUXEMBOURG | LU |
| MACAU, CHINA | MO | MACEDONIA, REPUBLIC OF | MK |
| MADAGASCAR | MG | MALAWI | MW |
| MALAYSIA | MY | MALDIVES | MV |
| MALI | ML | MALTA | MT |
| MARSHALL ISLANDS | MH | MARTINIQUE | MQ |
| MAURITANIA | MR | MAURITIUS | MU |
| MAYOTTE | YT | MEXICO | MX |
| MICRONESIA, FEDERATED STATES OF | FM | MOLDOVA, REPUBLIC OF | MD |
| MONACO | MC | MONGOLIA | MN |
| MONTENEGRO, REPUBLIC OF | ME | MONTSERRAT | MS |
| MOROCCO | MA | MOZAMBIQUE | MZ |
| MYANMAR | MM | NAMIBIA | NA |
| NAURU, REPUBLIC OF | NR | NEPAL | NP |
| THE NETHERLANDS | NL | NEVIS | XN |
| NEW CALEDONIA | NC | NEW ZEALAND | NZ |
| NICARAGUA | NI | NIGER | NE |
| NIGERIA | NG | NIUE | NU |
| NORWAY | NO | OMAN | OM |
| PAKISTAN | PK | PALAU | PW |
| PANAMA | PA | PAPUA NEW GUINEA | PG |
| PARAGUAY | PY | PERU | PE |
| PHILIPPINES, THE | PH | POLAND | PL |
| PORTUGAL | PT | PUERTO RICO | PR |
| QATAR | QA | REUNION, ISLAND OF | RE |
| ROMANIA | RO | RUSSIAN FEDERATION | RU |
| RWANDA | RW | SAMOA | WS |
| SAN MARINO | SM | SAO TOME AND PRINCIPE | ST |
| SAUDI ARABIA | SA | SENEGAL | SN |
| SERBIA | RS | SEYCHELLES | SC |
| SAINT HELENA | SH | SIERRA LEONE | SL |
| SINGAPORE | SG | SLOVAKIA | SK |
| SLOVENIA | SI | SOLOMON ISLANDS | SB |
| SOMALIA | SO | SOMALILAND, REP OF (NORTH SOMALIA) | XS |
| SOUTH AFRICA | ZA | SOUTH SUDAN | SS |
| SPAIN | ES | SRI LANKA | LK |
| ST. BARTHELEMY | XY | ST. EUSTATIUS | XE |
| ST. KITTS | KN | ST. LUCIA | LC |
| ST. MAARTEN | XM | ST. VINCENT | VC |
| SUDAN | SD | SURINAME | SR |
| SWAZILAND | SZ | SWEDEN | SE |
| SWITZERLAND | CH | SYRIA | SY |
| TAHITI | PF | TAIWAN, CHINA | TW |
| TAJIKISTAN | TJ | TANZANIA | TZ |
| THAILAND | TH | TOGO | TG |
| TONGA | TO | TRINIDAD AND TOBAGO | TT |
| TUNISIA | TN | TURKEY | TR |
| TURKS AND CAICOS ISLANDS | TC | TUVALU | TV |
| UGANDA | UG | UKRAINE | UA |
| UNITED ARAB EMIRATES | AE | UNITED KINGDOM | GB |
| UNITED STATES OF AMERICA | US | URUGUAY | UY |
| UZBEKISTAN | UZ | VANUATU | VU |
| VENEZUELA | VE | VIETNAM | VN |
| VIRGIN ISLANDS (BRITISH) | VG | VIRGIN ISLANDS (US) | VI |
| YEMEN, REPUBLIC OF | YE | ZAMBIA | ZM |
| ZIMBABWE | ZW | VATICAN CITY | VA |
| CHINA | CN | TURKMENISTAN | TM |

**Errors (master superset table)**

| Code | Meaning |
|---|---|
| 200 | Request Success |
| 1000 | Forbidden IP |
| 1001 | Invalid Token – unable to retrieve relevant information |
| 1002 | Too frequent request |
| 1003 | Server Error |
| 1004 | Request Path Error |
| 2000 | Incomplete Parameter |
| 2001 | File Url is invalid |
| 2002 | Exceed the File Size limitation |
| 2003 | Exceeds file name length or contains unsupported format |
| 2004 | orderType is null or invalid |
| 2005 | Batch number does not exist or cannot be bound |
| 2006 | File error |
| 2007 | File upload error |
| 2008 | File contains sensitive content |
| 2009 | Unsupported business type |
| 2099 | Only "ENIG-RoHS" surface finish is allowed for 0.4mm PCB thickness |
| 2100 | PCB layer value error |
| 2101 | PCB length format error or length exceeds 5 |
| 2102 | PCB width format error or width exceeds 5 |
| 2103 | PCB quantity parameter error |
| 2104 | PCB thickness format error |
| 2105 | PCB solder mask color format error |
| 2106 | Surface finish format error |
| 2107 | Copper weight format error |
| 2108 | Gold finger format error |
| 2109 | Material details format error |
| 2110 | Incomplete Parameter of Panel By JLCPCB |
| 2111 | Different design panel quantity error |
| 2112 | Remark exceeds maximum character length |
| 2113 | PCB order for given UuiD does not exist |
| 2114 | SMT stencil valid area is smaller than PCB |
| 2115 | Parameters restrict placing the order |
| 2116 | Exceed PCB size (too large) |
| 2117 | Order does not meet backend restriction, check detailed tips |
| 2118 | billingAddressFlag can't be null, 1 or 0 |
| 2119 | panelFlag cannot be null or incorrect |
| 2120 | PCB half-hole parameter is incorrect |
| 2121 | Flying probe test value error |
| 2122 | Purple PCB ordering limitation |
| 2123 | Single-layer PCB cannot support half-hole |
| 2200 | Stencil dimensions ID does not exist |
| 2201 | Stencil quantity error |
| 2202 | Electro-polishing not supported |
| 2203 | Fiducial mark through-hole parameter error |
| 2204 | steelPurpose type parameter error |
| 2205 | Stencil side parameter error |
| 2206 | Stencil remark exceeds character limit |
| 2207 | Stencil order for given UUID does not exist |
| 2208 | Custom size parameter error |
| 2209 | Quantity must be at least 2 when selecting "Top & Bottom (On Separate Stencil)" |
| 2210 | customizeFlag cannot be null or contain invalid value |
| 2300 | Shipping method parameter error |
| 2301 | Shipping method is null or not available for destination country |
| 2302 | Exceed the maximum weight for the selected shipping method |
| 2399 | Tax/VAT number exceeds 32 characters |
| 2400 | Tax/VAT number is required for Brazil |
| 2401 | shippingAddress.firstName is null or exceeds character length |
| 2402 | shippingAddress.lastName is null or exceeds character length |
| 2403 | shippingAddress.companyName exceeds character length limit |
| 2404 | shippingAddress.streetAddress is null or exceeds character length |
| 2405 | shippingAddress.addressLine2 exceeds character length limit |
| 2406 | shippingAddress.city is null or exceeds character length |
| 2407 | shippingAddress.province is null or exceeds character length |
| 2408 | shippingAddress.postalCode is null or exceeds character length or does not meet the request |
| 2409 | shippingAddress.cellOrMobileNumber is null or exceeds character length |
| 2410 | ShippingAddress.country is null or exceeds character length or does not exist |
| 2411 | billingAddress.firstName is null or exceeds character length |
| 2412 | billingAddress.lastName is null or exceeds character length |
| 2413 | billingAddress.companyName exceeds character length limit |
| 2414 | billingAddress.streetAddress is null or exceeds character length |
| 2415 | billingAddress.addressLine2 exceeds character length limit |
| 2416 | billingAddress.city is null or exceeds character length |
| 2417 | billingAddress.province is null or exceeds character length |
| 2418 | billingAddress.postalCode is null or exceeds character length or does not meet the request |
| 2419 | billingAddress.cellOrMobileNumber is null or exceeds character length |
| 2420 | billingAddress.country is null or exceeds character length or does not exist |
| 2500 | Key_cannot_be_found_error — The key data cannot be found |
| 2501 | No_audit_result — No audit result yet |
| 2601 | The combined specifications you selected cannot be processed because there are not enough orders to combine on a panel |
| 2602 | The achieve date error |
| 2603 | The impedance error |
| 2604 | The Layer to impedance error (Layer-to-impedance mismatch) |
| 2605 | The Cascade Structure (Stack-up) error |
| 2606 | The Cascade Structure (Stack-up) Color error |
| 2701 | High-end personalized process not enabled |
| 2702 | High-end personalized process code cannot be empty |
| 2703 | High-end personalized process option value cannot be empty |
| 2704 | High-end personalized process option value error (does not exist) |
| 2705 | High-end personalized process code value error (does not exist) |
| 2706 | 1-layer PCB does not support personalized features (e.g., 4-wire Kelvin test, min hole size/diameter) |
| 2707 | 2-layer PCB does not support personalized min hole size/diameter |
| 2801 | Board type error |
| 2802 | Aluminum PCB solder mask color error. (The Plate type to color error) |
| 2803 | Aluminum PCB can only be single-layer. (The Plate type to Layer error) |
| 2804 | Aluminum PCB thickness must be 1.0, 1.2, or 1.6mm. (The Plate type to Thickness error) |
| 2805 | Aluminum PCB supports only 1 oz copper weight. (The Plate type to Copper Weight error) |
| 2806 | Aluminum PCB supports only HASL surface finish. (The Plate type to Surface Finish error) |
| 2807 | Aluminum PCB does not support personalized processes. (The Plate type to High and personalized error) |
| 2808 | Aluminum PCB does not support 45° gold finger beveling. (The plate Type to 45° gold finger error) |
| 3000 | blind slots info is null |
| 3001 | Blind slots only supports FR-4 base material |
| 3002 | Blind slot not supported on this PCB layer |
| 3003 | Blind slot not supported for this PCB's thickness |
| 3004 | Blind slot quantity error (max 3, min 1) |
| 3005 | Blind slots info error |
| 5000 | Process Validation Failed — Displays the specific process exception |
| 5001 | File Parsing Failed — EDA design files are not supported |
| 5002 | The file parsing indicates that it is not designed with EasyEDA and does not support EDA design discounts. |
| 5004 | API does not support colorful silkscreen |
| 5005 | The Prefix option for the 2D barcode (Serial Number) process exceeds the character limit. |
| 5006 | The Incrementing Number option for the 2D barcode (Serial Number) process exceeds the character limit. |

**Example**

Request:
```json
{
  "orderType": 1,
  "pcbParam": {
    "layer": 2,
    "length": 72,
    "width": 71,
    "qty": 100,
    "thickness": 1.6,
    "pcbColor": 0,
    "surfaceFinish": 2,
    "copperWeight": 1,
    "goldFinger": 2,
    "materialDetails": 0,
    "panelFlag": 0,
    "panelByJLCPCB_X": 0,
    "panelByJLCPCB_Y": 0,
    "differentDesign": 1,
    "orderDetailsRemark": "1234 客户备注",
    "cascadeStructure": 1,
    "impedanceFlag": "no",
    "serviceConfigVos": [
      { "serviceConfigCode": "PPBP", "serviceConfigShow": "Paper between PCBs", "configOptionShow": "No" },
      { "serviceConfigCode": "CPF", "serviceConfigShow": "Confirm Production file", "configOptionShow": "No" }
    ]
  },
  "achieveDate": 120,
  "fileKey": ""
}
```
Response:
```json
{
  "code": 200,
  "message": null,
  "data": {
    "orderTotalWeight": 500.0,
    "priceWithoutFreight": 200.50,
    "pcbCostInfo": {
      "weight": 400.0, "totalFee": 180.00, "projectFee": 10.00, "spellFee": 5.00,
      "adornPutFee": 3.00, "stencilFee": 20.00, "testsFee": 15.00, "fillFee": 2.00,
      "achieveFee": 8.00, "charFontColor": 1.00, "halfHoleFee": 4.00, "bigBoardFee": 6.00,
      "cuprumThicknessFee": 7.00, "insideCuprumThicknessFee": 5.00, "rimCutFee": 3.00,
      "specialProcessMoney": 9.00, "noCodeMoney": 0.00, "stackupMoney": 12.00,
      "viaCoveringMoney": 4.00, "goldThicknessMoney": 10.00, "edgeGrindingMoney": 3.50,
      "dummyMoney": 2.00, "specialMoney": 0.00, "specialFlag": false, "originStencilMoney": 18.00
    },
    "originPcbCostInfo": {
      "weight": 400.0, "totalFee": 170.00, "projectFee": 10.00, "spellFee": 5.00,
      "adornPutFee": 3.00, "stencilFee": 20.00, "testsFee": 15.00, "fillFee": 2.00,
      "achieveFee": 8.00, "charFontColor": 1.00, "halfHoleFee": 4.00, "bigBoardFee": 6.00,
      "cuprumThicknessFee": 7.00, "insideCuprumThicknessFee": 5.00, "rimCutFee": 3.00,
      "specialProcessMoney": 9.00, "noCodeMoney": 0.00, "stackupMoney": 12.00,
      "viaCoveringMoney": 4.00, "goldThicknessMoney": 10.00, "edgeGrindingMoney": 3.50,
      "dummyMoney": 2.00, "specialMoney": 0.00, "specialFlag": false, "originStencilMoney": 18.00
    },
    "smtStencilCostInfo": { "weight": 100.0, "totalFee": 30.00 },
    "shipList": [
      { "options": "express", "showOptions": "Express Delivery", "cost": "20.00", "day": "3" },
      { "options": "standard", "showOptions": "Standard Delivery", "cost": "10.00", "day": "5" }
    ],
    "achieveDateList": [
      { "achieveName": "Normal", "achieveDate": "48", "achieveChecked": "true", "achievePrice": 0.00 },
      { "achieveName": "Urgent", "achieveDate": "24", "achieveChecked": "false", "achievePrice": 10.00 }
    ],
    "serviceConfigInfoList": [
      {
        "serviceConfigCode": "SERVICE_001",
        "serviceConfigShow": "Service Option 1",
        "configOptionInfoList": [
          { "configOptionShow": "OPTION_A", "defaultOption": true },
          { "configOptionShow": "OPTION_B", "defaultOption": false }
        ]
      }
    ],
    "serviceConfigFeeInfo": [
      { "serviceConfigCode": "SERVICE_001", "serviceConfigShow": "Service Option 1", "serviceFee": 5.00, "configOptionName": "OPTION_A", "configOptionShow": "Option A Description" },
      { "serviceConfigCode": "SERVICE_002", "serviceConfigShow": "Service Option 2", "serviceFee": 8.00, "configOptionName": "OPTION_C", "configOptionShow": "Option C Description" }
    ],
    "gerberTop": "http://example.com/gerber/top.png",
    "gerberBottom": "http://example.com/gerber/bottom.png"
  }
}
```

---

### `POST /overseas/openapi/pcb/audit/get` — PCB Pre-review Information

**Hendley:** `JLCClient.get_pcb_audit_info(key)`

Retrieve the pre-production (DFM/review) result for an uploaded Gerber file.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| key | string | yes | Gerber File Identification |
| language | Int | no | 0 English, 1 Korean, 2 Japanese, 3 Turkish |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| stencilLayer | string | Board Layer |
| minLineWidth | Number | Minimum line width |
| minLineDist | Number | Minimum line distance |
| smallestHole | Number | Minimum aperture (PDF type spelled `Nmber`) |
| setLength | Number | Length |
| setWidth | Number | Width |
| technologyDiscernRecordResult | Map<String,List> | Review Information (keyed by red/blue/green/yellow buckets) |
| url | string | Gerber view URL |
| gerberTop | string | Top Layer Image |
| gerberBottom | string | Bottom Layer Image |

**Errors**

| Code | Meaning |
|---|---|
| 200 | Request Success |

> Note: 200 only documented (the PDF's error table lists only 200).

**Example**

Request:
```json
{
  "key": "c003ed63e2cb45d38df2134870d91e23",
  "language": 1
}
```
Response:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "stencilLayer": 2,
    "minLineWidth": 10,
    "minLineDist": 7.86,
    "smallestHole": 0.5,
    "setLength": 106.9,
    "setWidth": 43.05,
    "technologyDiscernRecordResult": {
      "red": [],
      "blue": [
        "FF-NFX-MIFA-R3.DRR(null): Non-gerber274X/excellon formats",
        "FF-NFX-MIFA-R3.GM1(null): Non-gerber274X/excellon formats",
        "FF-NFX-MIFA-R3.LDP(null): Non-gerber274X/excellon formats",
        "FF-NFX-MIFA-R3.RUL(null): Non-gerber274X/excellon formats",
        "FF-NFX-MIFA-R3.GKO(Board Outline Layer):Gerber file with a board outline",
        "FF-NFX-MIFA-R3.GPT(null): Non-critical Gerber file",
        "FF-NFX-MIFA-R3.GPB(null): Non-critical Gerber file"
      ],
      "green": [
        "FF-NFX-MIFA-R3.GTO(Top Silkscreen):Generic Gerber file",
        "FF-NFX-MIFA-R3.GTP(Top Solder Paste):Generic Gerber file",
        "FF-NFX-MIFA-R3.GTS(Top Soldermask):Generic Gerber file",
        "FF-NFX-MIFA-R3.GTL(Top Layer):Generic Gerber file",
        "FF-NFX-MIFA-R3.GBL(Bottom Layer):Generic Gerber file",
        "FF-NFX-MIFA-R3.GBS(Bottom Soldermask):Generic Gerber file",
        "FF-NFX-MIFA-R3.GBP(Bottom Solder Paste):Generic Gerber file",
        "FF-NFX-MIFA-R3.GBO(Bottom Silkscreen):Generic Gerber file",
        "FF-NFX-MIFA-R3.TXT(Drill Layer):Generic Gerber file",
        "FF-NFX-MIFA-R3.GM13(null):Generic Gerber file",
        "FF-NFX-MIFA-R3.GM15(null):Generic Gerber file"
      ],
      "yellow": []
    },
    "url": "http://test.sz-jlc.com/quote/gerberview/c0609c52-0fe4-4e93-926a-b6805a3e85d2_1_0_1_0_1.html",
    "gerberTop": "https://test.jlcpcb.com//quote/downImg?color=Green&uuid=dc295bd3-8ef5-4833-88a4-0de27b2ee4e3&small=2&type=top&fromDemo=",
    "gerberBottom": "https://test.jlcpcb.com//quote/downImg?color=Green&uuid=dc295bd3-8ef5-4833-88a4-0de27b2ee4e3&small=2&type=bottom&fromDemo="
  }
}
```

---

### `POST /overseas/openapi/pcb/order/detail` — Order Information Query API

**Hendley:** `JLCClient.get_order_detail_by_batch_num(batch_num)`

Query full order detail (address, costs, PCB/stencil items) by batch number.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| batchNum | string | yes | Batch number |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| orderAddress | OrderAddressData | Shipping address (JSON example key: `shippingAddress`) |
| shippingMethod | string | Shipping method |
| paymentMethod | string | Payment Method |
| totalDummyMoney | Number | Merchandise cost |
| totalCarriageMoney | Number | Shipping cost |
| totalMoney | Number | Order total cost |
| orderItem | List<OrderItemData> | Order item list |

**`orderAddress` — OrderAddressData**

| Field | Type | Description |
|---|---|---|
| city | String | City |
| province | String | Province / State |
| linkAddress | String | Shipping address |

**`orderItem[]` — OrderItemData**

| Field | Type | Description |
|---|---|---|
| orderType | Int | Order Type: 1-PCB, 3-Stencil |
| pcbItem | PCBItem | PCB Order Details |
| smtItem | SMTItem | Stencil Order Details |

**`pcbItem` — PCBItem**

| Field | Type | Description |
|---|---|---|
| fileName | String | Gerber file name |
| buildTime | Int | Build time |
| count | Int | Quantity |
| orderDate | String | Order Date |
| orderFileUrl | String | Download URL of Order File |
| produceCode | String | Order Number |
| customerCode | String | Customer Code |
| orderRemark | String | Order Remarks |
| deliveryTime | String | Shipment Date |
| price | Number | Order Cost |
| orderStatus | Int | Order Status: 0-Cancelled, 1-Pending Review, 2-Awaiting Confirmation, 3-Confirmed, 4-Submitted to the factory, 5-Shipped |
| cancelReason | String | Review failed reason |
| cancelImgPath | String | Review failed image |
| layer | Int | PCB Layers |
| width | Number | PCB width |
| length | Number | PCB length |
| thickness | Number | PCB thickness |
| pcbColor | String | Solder mask color. Options: Green, Red, Yellow, Blue, White, Black, Purple |
| surfaceFinish | String | Surface Finish. HASL(with lead): Hot Air Solder Leveling with Lead; LeadFree HASL-RoHS: Lead-Free HASL (RoHS Compliant); ENIG-RoHS: Electroless Nickel Immersion Gold (RoHS) |
| copperWeight | Number | Copper Weight |
| goldFinger | String | Gold Finger. "0":No, "2": Yes (45 chamfered border) |
| materialDetails | String | Base Material. FR4-Standard Tg 140C |
| panelFlag | int | Custom Panelization Flag (1 - Custom, 0 - Not Custom) |
| panelByJLCPCB_X | int | Panel Count on X-axis (if panelized by JLCPCB) |
| panelByJLCPCB_Y | int | Panel Count on Y-axis (if panelized by JLCPCB) |
| differentDesign | int | Number of Designs in Panel |
| testProduct | String | Flying probe test: 0-No Test, 1-Sample Test, 2-100% Test, 6-Fixture Test (Engineering Jig) |
| halfHole | String | Is it Castellated Holes? yes / no |
| halfHoleNumber | int | Number of holes |
| testsMoney | Number | Flying probe test amount |
| halfHoleMoney | Number | Castellated Holes Fee |
| insideCuprumThickness | Number | Inner Layer Copper Thickness (PDF labels "Inside Cuprum Thickness") |

**`smtItem` — SMTItem**

| Field | Type | Description |
|---|---|---|
| fileName | String | Gerber file name |
| buildTime | Int | Build Time |
| count | Int | Quantity |
| orderDate | String | Order Date |
| orderFileUrl | String | Download URL of Order File |
| produceCode | String | Order Number |
| customerCode | String | Customer Code |
| orderRemark | String | Order Remarks |
| deliveryTime | String | Shipment Date |
| price | Number | Order Cost |
| orderStatus | Int | Order Status: 0-Cancelled, 1-Pending review, 2-Awaiting Confirmation, 3-Confirmed, 4-Submitted to the factory, 5-Shipped |
| cancelReason | String | Audit failure reason |
| cancelImgPath | String | Review failed image |
| length | Number | Stencil length |
| width | Number | Stencil width |
| stencilSide | String | Stencil Side: Top+Bottom (On Single Stencil), Top, Bottom, Top & Bottom (On Separate Stencil) |

**Errors**

| Code | Meaning |
|---|---|
| 200 | Request Success |

> Note: 200 only documented.

**Example**

Request:
```json
{
  "batchNum": "W20250124457855"
}
```
Response:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "shippingAddress": { "city": "aa", "province": "aa", "linkAddress": "aaa a" },
    "shippingMethod": "dhl",
    "paymentMethod": "paypal",
    "totalDummyMoney": 5,
    "totalCarriageMoney": 18.46,
    "totalMoney": 36.92,
    "orderItem": [
      {
        "orderType": 1,
        "pcbItem": {
          "fileName": "aaaaa_Y177",
          "buildTime": 48,
          "count": 10,
          "orderDate": "2018-09-18 09:37:35",
          "orderFileUrl": "/file/download?uuid=d62df099f54b44ad962108f18634c3db&businessType=example",
          "produceCode": "Y177",
          "customerCode": "2352311A",
          "orderRemark": "",
          "deliveryTime": null,
          "price": 5,
          "orderStatus": 7,
          "cancelReason": null,
          "cancelImgPath": null,
          "layer": 2,
          "width": 1,
          "length": 1,
          "thickness": 1.6,
          "pcbColor": "Green",
          "surfaceFinish": "HASL(with lead)",
          "copperWeight": 1,
          "goldFinger": "2",
          "materialDetails": "FR4-Standard Tg 140C",
          "panelFlag": 0,
          "panelByJLCPCB_X": null,
          "panelByJLCPCB_Y": null,
          "differentDesign": 1
        },
        "smtItem": {
          "fileName": null, "buildTime": null, "count": null, "orderDate": null,
          "orderFileUrl": null, "produceCode": null, "customerCode": null,
          "orderRemark": null, "deliveryTime": null, "price": null, "orderStatus": null,
          "cancelReason": null, "cancelImgPath": null, "stencilSide": null,
          "length": null, "width": null
        }
      }
    ]
  }
}
```

---

### `POST /overseas/openapi/pcb/wip/get` — PCB Production Progress Query

**Hendley:** `JLCClient.get_pcb_wip_process(order_uuid)`

Query production (work-in-process) progress steps for an order.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| orderUUID | string | yes | Order ID |

**Response `data`** (array; the example key is `date` [sic])

| Field | Type | Description |
|---|---|---|
| technicsProcessName | string | Process Name |
| beginTime | String | Start time |

**Errors**

| Code | Meaning |
|---|---|
| 200 | Request Success |

> Note: 200 only documented. The response example uses the key `"date"` (not `"data"`).

**Example**

Request:
```json
{
  "orderUUID": "weiuyqwhuiwqh"
}
```
Response:
```json
{
  "code": 200,
  "date": [
    { "technicsProcessName": "xxxx", "beginTime": "xxxx" }
  ]
}
```

---

### `POST /overseas/openapi/pcb/create` — Create an order

**Hendley:** `JLCClient.create_pcb_order(...)`

Place a PCB and/or stencil order from an uploaded Gerber and craft parameters.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| fileKey | string | yes | Identifier for the Gerber file |
| batchNum | string | no | Batch number. When there is no need to combine order, omit; passing an empty string indicates a document needs to combine order. |
| shippingAddress | OrderAddressData | yes | Shipping address |
| billingAddress | OrderAddressData | no | Billing Address. Required when billingAddressFlag is 1; when billingAddressFlag is 0, shippingAddress is used |
| taxOrVATNumber | string | yes | Tax or VAT number |
| billingAddressFlag | boolean | yes | Whether to use billing address: 0 – Do not use, 1 – Use |
| orderType | int | yes | Order type: 1 – PCB only, 2 – PCB + stencil, 3 – Stencil only |
| pcbParam | PcbOrderCraftData | no | PCB process parameters |
| smtStencilParam | SteelOrderCraftData | no | Stencil process parameters |
| achieveDate | int | no | lead time |
| shippingMethod | string | yes | Shipping method |

**`shippingAddress` / `billingAddress` — OrderAddressData**

| Field | Type | Required | Description |
|---|---|---|---|
| firstName | string | yes | First name |
| lastName | string | yes | Last name |
| companyName | string | no | Company name |
| streetAddress | string | yes | Street address |
| addressLine2 | string | yes | Additional detailed address |
| city | string | yes | City |
| country | string | yes | Country |
| province | string | yes | Province |
| postalCode | string | yes | Postal code / ZIP code |
| cellOrMobileNumber | string | yes | Phone number |

**`pcbParam` — PcbOrderCraftData**

Same structure as the `calculate` PcbOrderCraftData. Fields:

| Field | Type | Required | Description |
|---|---|---|---|
| layer | Integer | yes | Number of PCB layers |
| width | Number | yes | PCB width (mm) |
| length | Number | yes | PCB length (mm) |
| qty | int | yes | PCB quantity |
| thickness | Number | yes | PCB thickness |
| pcbColor | Int | yes | PCB color (Solder mask): 0-green, 1-red, 2-yellow, 3-blue, 4-White, 5-black, 6-Purple |
| surfaceFinish | Int | yes | Surface finish: 0 – HASL with lead, 1 – Lead-free HASL, 2 – ENIG |
| copperWeight | Number | yes | Outer layer copper weight (oz) |
| insideCuprumThickness | string | yes | Inner layer copper thickness (PDF labels "Inside Cuprum Thickness") |
| goldFinger | Int | yes | 0-Gold fingers / 0 – Not required, 1 – Required, 2 – Required with bevel edge |
| materialDetails | Int | yes | Material type: 0 – FR4 Standard Tg 140°C |
| panelFlag | int | yes | Is the number of panels customized? 1- Panel by JLCPCB, 0- Single PCB, 2- Panel by Customer |
| panelByJLCPCB_X | Int | yes | Panel count on X axis (required if Panel by JLCPCB or Panel by Customer) |
| panelByJLCPCB_Y | Int | yes | Panel count on Y axis (required if Panel by JLCPCB or Panel by Customer) |
| differentDesign | Int | yes | Number of different designs per panel (Single PCB or Panel by JLCPCB, default 1) |
| flyingProbeTest | Int | yes | Flying probe test type: 0 – No test, 1 – Sample test, 2 – 100% test, 6 – Fixture test |
| castellatedHoles | Int | yes | Number of castellated holes: 0, 1, 2, 3, 4 |
| orderDetailsRemark | String | yes | Order detailed remarks |
| cascadeStructure | Int | yes | Stack-up structure type: 0, 1, 2 |
| impedanceTemplateCode | String | no | Impedance Template Code — obtain from getImpedanceTemplateSettingList (by PCB layer, thickness, inner & outer copper thickness, base material) |
| impedanceFlag | String | yes | Is impedance required? yes / no |
| isAddCustomerCode | String | yes | Add customer code on board? yes – Add at specified location; Yes – no location specified; nocode – Do not add code |
| plateType | Int | yes | Base material type: 1-FR-4, 2-Aluminum, 4-Copper Core, 5-Rogers, 6-PTFE Teflon, 7-Flex (FPC) |
| autoConfirmProductionFile | Boolean | yes | Is the production file automatically confirmed? |
| markOnPcb | Int | yes | Add Mark on PCB? 1 – No marking, 2 – Add customer code (no location specified), 3 – Add customer code (at specified location), 4 – Add Serial number QR code |
| viaCovering | Int | yes | Via covering type: 1 – Tented, 2 – Untented, 3 – Plugged, 4 – Epoxy Filled&Capped, 5 – Copper paste filled&Capped |
| needTechnics | Int | yes | Need Technics (edge Processing)? 0 – No, 1 – Two sides, 2 – Four sides, 3 – Top and bottom, 4 – Left and right. Single PCB or Panel by Customer, default 0 |
| technicsSize | Int | no | Technics Size (mm) — Required when needTechnics is 1, 2, 3, or 4; default 0 |
| goldThickness | Number | no | ENIG Thickness — Required when surfaceFinish is 2 |
| edgeRounding | Boolean | yes | Is edge rounding required? |
| rowSpacing | Number | no | Row spacing (mm) |
| columnSpacing | Number | no | Column spacing (mm) |
| serviceConfigVos | List<PcbOrderServiceCraftData> | yes | Advanced customization information |
| pcbBlindViaHoleInfoDTOList | List<PcbBlindViaHoleData> | no | Blind Slot Information — Required when serviceConfigVos contains [serviceConfigCode=BVH, serviceConfigShow=Blind Slots, configOptionShow=Yes] |
| edaSoftware | String | no | Design Software — [Other, EasyEDAPro]; Flex(FPC) only; default Other |
| fpcGoldFingerThickness | Number | no | Flex(FPC) gold finger thickness (0.1–1 mm) when serviceConfigVos contains GF_CT Gold Fingers Yes; else default 0 |
| serialQrCodeConfigData | SerialQrCodeConfigData | no | QR Code Related Parameters |

**`serialQrCodeConfigData` — SerialQrCodeConfigData**

| Field | Type | Required | Description |
|---|---|---|---|
| qrCodeFormat | Integer | no | QR code formats: 1-QR, 2-DM |
| qrLocation | Integer | no | QR code location: 1 - No requirement, 2 - Specify Position |
| prefixCode | string | no | Prefix Code. 5*5: up to 19 chars; 8*8: up to 34; 10*10: up to 69; Plain Code Only: up to 7 |
| addUniqueCode | Boolean | no | Add a unique code? |
| incrCode | string | no | Incremental Code. QR Code Only: up to 6 chars; Plain Code Only: up to 7 chars |

**`serviceConfigVos[]` — PcbOrderServiceCraftData**

| Field | Type | Required | Description |
|---|---|---|---|
| serviceConfigCode | string | yes | Customization configuration code |
| serviceConfigShow | string | yes | Display name of the customization configuration |
| configOptionShow | string | yes | Display name of the selected customization option |

**`pcbBlindViaHoleInfoDTOList[]` — PcbBlindViaHoleData**

| Field | Type | Required | Description |
|---|---|---|---|
| idnex | int | yes | Blind slot index (e.g., 1, 2, 3) (PDF spelling: `idnex`) |
| holeAttribute | Int | yes | Hole attribute: 1 – Non-plated (no copper), 2 – Plated (with copper) |
| layerLevel | Int | yes | Layer position: 1 – Top layer, 2 – Bottom layer |
| holeDepth | Number | yes | Hole depth |
| customerRemark | String | yes | Customer remarks |
| fileInfoList | FileData | yes | File information |

**`fileInfoList` — FileData**

| Field | Type | Required | Description |
|---|---|---|---|
| fileStoreId | String | yes | Blind slot image identifier |
| fileName | String | yes | File name |

**`smtStencilParam` — SteelOrderCraftData**

| Field | Type | Required | Description |
|---|---|---|---|
| dimensionsID | Int | yes | Stencil pricing ID |
| stencilQty | int | yes | Stencil Quantity |
| Electropolishing | int | yes | Electropolishing option: 0: No |
| fiducials | int | yes | Fiducial mark type: 0: No Fiducial, 1: Etched Through, 2: Etched Half into board |
| steelPurpose | String | yes | Stencil Process Type: solder_paste – Solder Paste, red_glue – Red Glue |
| customizeFlag | int | yes | Is Stencil dimension customized? 1: customize size, 0: don't customize |
| customizeSizeX | int | no | Custom width (X axis, in mm) |
| customizeSizeY | int | no | Custom height (Y axis, in mm) |
| stencilSide | int | yes | Stencil sides: 0: Top + Bottom (single stencil), 1: Top only, 2: Bottom only, 3: Top & Bottom (separate stencils) |
| orderRemark | string | no | Add remarks for stencil order |
| confirmFile | boolean | yes | Is production file confirmed? |
| autoConfirmProductionFile | int | no | Is production file automatically confirmed? 1: Yes, 0: No |
| moreShapeFlag | boolean | no | Multiple PCBs on one stencil (PDF type spelled `booleam`) |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| orderId | string | Order ID |
| orderType | int | Order type: 1 – PCB only, 2 – PCB + Stencil, 3 – Stencil only |
| orderDate | string | Order created date |
| batchNum | string | Batch number |

**Errors**

Same superset table as `calculate` (codes 200, 1000–1004, 2000–2009, 2099,
2100–2123, 2200–2210, 2300–2302, 2399, 2400–2420, 2500–2501, 2601–2606,
2701–2707, 2801–2808, 3000–3005, 5000–5006). See the `calculate` master error
table above for the full list of meanings (identical wording).

**`serviceConfigVos` customization-options catalog** (appendix; columns: Service
Config Name | Display Name (serviceConfigShow) | serviceConfigCode | Supported
Material | Config Option Name | Option display name (configOptionShow)). Selected
rows showing the code vocabulary:

| serviceConfigCode | serviceConfigShow | Material | Example option (configOptionShow) |
|---|---|---|---|
| mvhc | Min via hole size/diameter | FR4 | e.g. 0.2/0.4mm, 0.2/0.3mm, 0.25mm/(0.35/0.4mm), 0.15/0.25mm, 0.2/0.45mm↑ |
| PPBP | Paper between PCBs | — | Add Paper (yes) / No paper (No) |
| 4WKT | 4-Wire Kelvin Test | FR4, Rogers, Teflon | No / Yes |
| FT155 | Material Type | FR4 | FR4-Standard TG 135-140 (no requirement) / FR4 TG155 (TG155) |
| CPF | Confirm Production file | — | No / Yes |
| TH_CO | Thermal Conductivity | Aluminum PCB, Copper PCB | 1W / 380W / 381W |
| BR_VO | Breakdown Voltage | Aluminum PCB | 3000V |
| AQ | Appearance Quality | — | IPC Class 2 Standard / Superb Quality |
| SI_TE | Silkscreen Technology | FR4 | Ink-jet/Screen Printing Silkscreen / High-definition Exposure Silkscreen / High-precision Printing Silkscreen / EasyEDA multi-color silkscreen |
| OU_BO | X-out board | — | Not Accept / Accept |
| PK_BOX | Package Box | — | With JLCPCB logo / Blank box |
| CS | Direct Heatsink | Copper PCB | Thermal-Electrical Isolation / Direct Heatsink |
| HFMT | Material Type | Rogers/Teflon | RO4350B (Dk=3.48, Df=0.0037), ZYF300CA-P, ZYF300CA-C, ZYF265D, ZYF255DA |
| CT | Copper Type | FPC | Electro-deposited / Rolled Annealed |
| ESF | EMI Shielding Film | FPC | Without / Both sides (Black,18um) / Single side (Black,18um) |
| PBM | Polyimide base material | FPC | 25um |
| STT | Stainless Steel Thickness | FPC | No / 0.1mm / 0.2mm / 0.3mm |
| OT | Outline Tolerance | FPC | ±0.1mm / ±0.05mm |
| CM | Cutting Method | FPC | Laser Cutting / Punching |
| PIT | Polyimide Thickness | FPC | No / 0.1 / 0.15 / 0.20 / 0.225 / 0.25mm |
| CTC | Coverlay Thickness | FPC | PI:12.5um/AD:15um / PI:25um/AD:25um / PET:25um/AD:25um |
| FRT | FR4 Thickness | FPC | No / 0.1 / 0.2 / 0.4 / 0.6 / 0.8 / 1.0 / 1.2 / 1.6mm |
| 3MT | 3M Tape Thickness | FPC | No / 3M468 (0.13mm) / 3M9077 (HT, 0.05mm) |
| BOT | Board Outline Tolerance | FR4 | ±0.2mm(Regular) / ±0.1mm(Precision) |
| PYB | Coverlay Color | FPC | Yellow / Black / White / Transparent |
| SC_PR | Silkscreen on Stiffener | FPC | Yes / No |
| GF_CT | Gold Fingers | FPC / FR4 | Yes / No |
| OR_BR | order_plate_brand | FR4 | KB / Shengyi PCB Material / Taiwan Nanya PCB Material / No |
| ME_TR | Edge Plating | FR4 | No / Yes |
| WT_GR | Grounding / Ground wirer | FPC | Not grounded / grounded |
| PTH | Press-Fit Hole | FR4 | No / Yes (Tolerance +/-0.05mm) |
| N2B | Need 2D Barcode | FR4 | Don't Add / Specify Position / No Requirement |
| 2DBS | 2D Barcode Size | FR4 | 8*8mm / 10*10mm / 3*3mm / 5*5mm |
| QRCPT | QR Code Print Type | FR4 | 2D barcode & Number / Number Only / 2D barcode Only |
| IR | Inspection Report | FR4 | No / Reliability / ROHS / Nickel Corrosion / Final Inspection / SEM / Electrical Test / Microsection / Ionic Contamination |
| BVH | Blind Slots | FR4 | Yes / No |
| STACK UP | Stackup Type | FPC | Bonded / Unbonded |
| ST | Substrate Type | FPC | 25µm dielectric / 50µm dielectric / Transparent |
| IM_TR | Impedance Control | FR4 | No requirement / ±10% (±5Ω if value≤50Ω) |

**Example**

Request:
```json
{
  "orderType": 1,
  "fileKey": "16e894abb3fd49d78016e9046085730e",
  "pcbParam": {
    "materialDetails": 0,
    "panelFlag": 0,
    "pcbColor": 5,
    "qty": 5,
    "surfaceFinish": 2,
    "thickness": 1.6,
    "width": 207.0,
    "copperWeight": "2",
    "insideCuprumThickness": "1",
    "differentDesign": 1,
    "goldFinger": 0,
    "layer": 4,
    "length": 160.0,
    "goldThickness": 2,
    "isAddCustomerCode": "nocode",
    "viaCovering": 4,
    "flyingProbeTest": 2,
    "serviceConfigVos": [
      { "serviceConfigCode": "FT155", "serviceConfigShow": "Material Type", "configOptionShow": "FR-4 TG155" }
    ]
  },
  "shippingMethod": "inland_sf",
  "billingAddressFlag": 0,
  "shippingAddress": {
    "addressLine2": "11111",
    "cellOrMobileNumber": "18756183901",
    "city": "天津市",
    "country": "CN",
    "firstName": "测试",
    "lastName": "测试",
    "postalCode": "928933",
    "province": "天津市",
    "streetAddress": "天景路"
  },
  "taxOrVATNumber": "string"
}
```
Response:
```json
{
  "code": 200,
  "message": null,
  "data": {
    "orderId": "uwqyhenqwjehqw",
    "orderType": 2,
    "orderDate": "2025-06-26T15:30:00+08:00",
    "batchNum": "BATCH_001"
  }
}
```

### `POST /overseas/openapi/pcb/getSteelPriceConfig` — Steel/Stencil Price Config

**Hendley:** `JLCClient.get_steel_price_config(body=None)`

> Note: **No official "View Docs" PDF exists for this route** — it is present
> only in the SDK jar (`GetSteelPriceConfigRequest`). The request-body shape is
> unconfirmed, so `client.py` sends an empty body. The route is `POST` (the SDK
> route), *not* the `GET` an earlier draft of this doc guessed. Response data is
> `SteelPriceConfigData` (field list in the jar; no PDF to transcribe).


---

## TDP (3D-printing / JLC3DP) order endpoints

Reverse-engineered from the SDK jars + console PDFs; not exercised here. All
`POST` under `/overseas/openapi/tdp/api/`. The endpoints form an ordered
pipeline — see the intro note below.

# JLC3DP (3D printing / `tdp`) OpenAPI Reference

Reverse-/forward-transcribed from the seven official JLCPCB "JLC3DP" OpenAPI PDFs. Every endpoint is `POST` to `https://open.jlcpcb.com` with the path shown. All seven PDFs were checked: each one's stated **Request URL** is `https://open.jlcpcb.com/overseas/openapi/tdp/api/...` exactly as listed below.

**Cross-field dependency flow (stated by the PDFs):**

- **Upload → poll:** the upload interface returns a file id (in its `message` field); pass it to the poll interface as `fileAccessId`.
- **Poll → calculate/create:** the poll response's selectable ids (`materialAccessId`, `materialColorAccessId`, `materialDeliveryAccessId`, `modelAccessId`, craft `craftAccessId`/`craftAttributeAccessId`, and `fileAccessId`/`fileName`) feed both the calculate and create-order requests.
- **Calculate → create:** the calculate response's `expressDetailResults[]` supplies `freightMode` (= `expressName`) and `typeOfTrade` for the create-order request.
- **Poll customs cascade → create:** the poll response's `clearanceParamTreeDTOS` cascade supplies `goodsCustomsType` (= `clearanceParamTreeDTOS.children.value`) for the create-order request.
- **Create → list → detail/process:** create returns a `batchNum`; the order-list returns batches and per-order `orderNo`; `batchNum` feeds order-detail and `orderNo` feeds order-process.

**Envelope variants (oddities):**

- **Upload** returns the new id in the **`message`** field (not in `data`) alongside `"successful": true` — note the field name `successful`, not `success`.
- **Poll**, **calculate**, **order/list** examples show only `{code, data}` (no message field).
- **create**, **order/detail**, **order/process** use **`msg`** (e.g. `"msg": "Success"`) instead of `message`.
- All documented examples show success `code: 200` only — none of the seven PDFs include an error-code table.
- **None of the seven PDFs contain a Request example** — each PDF documents only a "Return Example." Every `Request:` block below is therefore constructed from the documented Body Parameters; fabricated/illustrative values are shown as `<placeholders>`, while ids/codes reused from the PDFs' own return examples (e.g. `8429f2bab...`, `dhl`, `W202310182134757`) are real PDF values.

---

### `POST /overseas/openapi/tdp/api/upload` — JLC3DP File Upload Interface

**Hendley:** `JLCClient.upload_tdp_file(file)`

Upload a 3D model file; after parsing the system returns model data, attributes (length, width, height), a list of selectable materials and manufacturing processes, and explanations for unavailable options.

> Note: this is a `multipart/form-data` file upload.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | yes | 3D printing model file. File formats limited to `stl`, `stp`, `step`, `obj`, `3mf`, `rar`, `zip`. File name cannot exceed 50 characters and file size cannot exceed 80MB. |
| `fileName` | String | no | File name. |

**Response `data`**

> Note: upload has no `data` object. The newly created file record id is returned in the **`message`** field, with `successful: true`.

| Field | Type | Description |
|---|---|---|
| `code` | Integer | Status code (200 on success). |
| `message` | String | The file record id (e.g. `"8701846449792143360"`) — pass as `fileAccessId` to the poll interface. |
| `successful` | Boolean | Whether the upload succeeded. |

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
// multipart/form-data
// field "file": <binary 3D model file>
// field "fileName": "RightCover.stl"   (optional)
```
> Note: multipart/form-data upload.

Response:
```json
{
  "code": 200,
  "message": "8701846449792143360",
  "successful": true
}
```

---

### `POST /overseas/openapi/tdp/api/file/result` — JLC3DP File Parsing Result (Polling Interface)

**Hendley:** `JLCClient.get_tdp_file_result(file_access_id)`

Get file parsing results by polling. After parsing the file, returns model data including dimensions (length, width, height), selectable materials and processes, and reasons for any unselectable options.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `fileAccessId` | String | yes | File record id — the file ID returned by the file upload interface. |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| `finishFlag` | Boolean | Is parsing completed? |
| `fileName` | String | File name. |
| `fileFormat` | String | File suffix. |
| `fileSize` | Integer | File size. |
| `businessType` | String | Business type (e.g. `tdpGoodsFile`). |
| `modelAccessId` | String | Model UUID. |
| `customerId` | Integer | Customer id. |
| `sizeX` | Number | Model length. |
| `sizeY` | Number | Model width. |
| `sizeZ` | Number | Model height. |
| `modelName` | String | Model name. |
| `modelVolume` | Number | Model volume. |
| `modelSurfaceArea` | Number | Model surface area. |
| `modelFace` | Integer | Model face. |
| `modelBrokenFace` | Integer | Model broken face. |
| `thumbnailUrl` | String | Thumbnail. |
| `previewUrl` | String | Preview image URL. |
| `imageName` | String | Image name. |
| `threeDimensionsMaterials` | Array&lt;Material&gt; | Material list (see sub-table). |
| `clearanceParamTreeDTOS` | Array&lt;ClearanceParamTree&gt; | Customs declaration parameters, cascade drop-down (see sub-table). |

**`threeDimensionsMaterials[]` — Material**

| Field | Type | Description |
|---|---|---|
| `batchDeliveryQuantity` | Number | Batch delivery quantity. |
| `batchDeliveryWeight` | Number | Batch delivery weight. |
| `batchMaterialDeliveryVOList` | Array | Batch material delivery list. |
| `dyeFlag` | Boolean | Whether to enable dyeing? |
| `dyeTypeId` | String | Dye type id. |
| `enableFlag` | Boolean | Is it selectable? |
| `materialAccessId` | String | Material UUID. |
| `materialCode` | String | Material code. |
| `materialColor` | String | Material color. |
| `materialColorList` | Array&lt;MaterialColor&gt; | Material color list (see sub-table). |
| `materialDeliveryVOList` | Array&lt;MaterialDelivery&gt; | Material delivery list (see sub-table). |
| `materialDensity` | Number | Material density. |
| `materialImageAccessId` | String | Material image UUID. |
| `materialIntroduce` | String | Material introduction. |
| `materialKeyId` | Integer | Material keyid. |
| `materialName` | String | Material name. |
| `materialSort` | Integer | Material sorting. |
| `materialStatus` | Integer | Material status: 0 Deleted, 1 Active, 2 Inactive. |
| `materialTechnicsId` | Integer | Material technology id. |
| `materialTechnicsName` | String | Material technology name (e.g. `SLA(Resin)`). |
| `materialTitle` | String | Material title. |
| `materialType` | String | Material type (e.g. `9000E Resin`). |
| `materialTypeId` | Integer | Material type id. |
| `materialUrgentLimit` | Object | Material urgent limit (see sub-table). |
| `modelSize` | Number | Model size. |
| `noCraft` | Boolean | Whether there is no surface finish? |
| `quotingCoefficient` | Number | Quoting coefficient. |
| `receiveOrderExplain` | String | Explanation for order acceptance limits. |
| `receiveOrderMax` | Number | Max daily accepted weight (kg). |
| `receiveOrderMaxG` | Number | Max daily accepted weight (g). |
| `receiveShopMax` | Integer | Max quantity per product per order. |
| `recommendFlag` | Boolean | Whether the material is marked as recommended? |
| `showColor` | Boolean | Whether to display the color on the front end? |
| `threeDimensionCraftColorRelationList` | Array&lt;CraftColorRelation&gt; | 3D surface finish list (see sub-table). |
| `todayTotalOrderWeight` | Number | Total weight ordered today (kg). |
| `todayTotalOrderWeightG` | Number | Total weight ordered today (g). |
| `unableReason` | String | Reason why the material is not selectable. |
| `volumeAccumulationCoefficient` | Number | Volume accumulation coefficient. |
| `weight` | Number | Weight per item. |

**`threeDimensionsMaterials[].materialColorList[]` — MaterialColor**

| Field | Type | Description |
|---|---|---|
| `colorBaseAccessId` | String | Basic color information UUID. |
| `materialColor` | String | Material color. |
| `materialColorAccessId` | String | Material color UUID. |
| `materialColorCn` | String | Material color (Chinese). |
| `materialColorDesc` | String | Material color description. |
| `materialColorValue` | String | Material color value. |
| `noCraft` | Boolean | Whether there is no surface finishing? |
| `quoteCoefficient` | Number | Quote coefficient. |
| `showColor` | Boolean | Whether to display the color on the front end? |

**`threeDimensionsMaterials[].materialDeliveryVOList[]` — MaterialDelivery**

| Field | Type | Description |
|---|---|---|
| `batchFlag` | Boolean | Whether delivery is based on batch threshold? |
| `deliveryCode` | String | Delivery code. |
| `deliveryDate` | Integer | Delivery time (hours). |
| `deliveryExplain` | String | Description. |
| `deliveryPostponeContent` | String | Backend-configured delivery delay message. |
| `deliveryTime` | Long | Delivery timestamp. |
| `deliveryType` | Integer | Delivery type: 1 Expedited, 2 Normal, 3 Other, 5 Holiday delivery. |
| `materialAccessId` | String | Material UUID. |
| `materialDeliveryAccessId` | String | Material delivery access ID. |
| `openFlag` | Boolean | Whether to enable? |
| `price` | Number | Price. |
| `startPrice` | Number | Starting price. |

**`threeDimensionsMaterials[].materialUrgentLimit` — MaterialUrgentLimit**

| Field | Type | Description |
|---|---|---|
| `nylonMaxCount` | Integer | Maximum number of nylon materials. |
| `nylonMaxHeight` | Integer | Maximum height of nylon material. |
| `nylonMaxLength` | Integer | Maximum length of nylon material. |
| `resinMaxHeight` | Integer | Maximum height of resin material. |
| `resinMaxLength` | Integer | Maximum length of resin material. |
| `resinMaxWeight` | Integer | Maximum weight of resin material. |

**`threeDimensionsMaterials[].threeDimensionCraftColorRelationList[]` — CraftColorRelation**

| Field | Type | Description |
|---|---|---|
| `colorBaseAccessId` | String | Color information UUID. |
| `defaultCraftAccessId` | String | Default surface finish uuid. |
| `noCraft` | Boolean | Whether there is no surface finish? |
| `threeDimensionCraftAttributeVOList` | Array&lt;CraftAttribute&gt; | Surface finish attribute list (see sub-table). |

**`...threeDimensionCraftAttributeVOList[]` — CraftAttribute**

| Field | Type | Description |
|---|---|---|
| `craftAccessId` | String | Craft UUID. |
| `craftAttributeAccessIdList` | Array&lt;String&gt; | Craft attribute uuid list. |
| `defaultSelectFlag` | Boolean | Whether to select by default? |
| `materialColorAccessId` | String | Material color UUID. |

**`clearanceParamTreeDTOS[]` — ClearanceParamTree (recursive cascade)**

| Field | Type | Description |
|---|---|---|
| `children` | Array&lt;ClearanceParamTree&gt; | Sub-items (recursive; `null` at leaf). |
| `label` | String | Option label (e.g. HS code description). |
| `sizeX` | Number | X size for the option (nullable). |
| `sizeY` | Number | Y size for the option (nullable). |
| `sizeZ` | Number | Z size for the option (nullable). |
| `value` | String | Option value — used as `goodsCustomsType` (via `children.value`) in create-order. |

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
{ "fileAccessId": "8701846449792143360" }
```
Response:
```json
{
  "code": 200,
  "data": {
    "finishFlag": true,
    "fileName": "RightCover",
    "fileFormat": "stl",
    "fileSize": 424784,
    "businessType": "tdpGoodsFile",
    "modelAccessId": "3f7fe2abea62421d87853dec054d8dfe",
    "customerId": 344491,
    "sizeX": 4.99,
    "sizeY": 1.84,
    "sizeZ": 3.58,
    "modelName": "RightCover",
    "modelVolume": 3.99,
    "modelSurfaceArea": 55.73,
    "modelFace": 0,
    "modelBrokenFace": 0,
    "thumbnailUrl": "tdpGoodsFilePreview_424a3fb8aea24441b995782cf0afc73c",
    "previewUrl": "https://test-tdpapi.jlcpcb.com/weapp/index.html#/model_preview/embedded?modelUrl=https://test-cart.jlcpcb.com/tdpFile/downloadTdpFile?fileAccessId=tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
    "imageName": "RightCover.PNG",
    "threeDimensionsMaterials": [
      {
        "batchDeliveryQuantity": null,
        "batchDeliveryWeight": null,
        "batchMaterialDeliveryVOList": [],
        "dyeFlag": false,
        "dyeTypeId": "0",
        "enableFlag": true,
        "materialAccessId": "8429f2bab5e7460b8713e8c7fabb622c",
        "materialCode": "L8",
        "materialColor": "LightGreen",
        "materialColorList": [
          {
            "colorBaseAccessId": "8835bb0e2efa47dbb2a708ee63b15d3f",
            "materialColor": "black",
            "materialColorAccessId": "d03377ef21904b269dd160b0e3bc331a",
            "materialColorCn": "Black",
            "materialColorDesc": "",
            "materialColorValue": "",
            "noCraft": false,
            "quoteCoefficient": 1.00,
            "showColor": false
          }
        ],
        "materialDeliveryVOList": [
          {
            "batchFlag": false,
            "deliveryCode": null,
            "deliveryDate": 48,
            "deliveryExplain": "1",
            "deliveryPostponeContent": null,
            "deliveryTime": 1697724000000,
            "deliveryType": 2,
            "materialAccessId": "8429f2bab5e7460b8713e8c7fabb622c",
            "materialDeliveryAccessId": "4b153b77173d4059a1a5073eb06eae5e",
            "openFlag": true,
            "price": 0.42,
            "startPrice": 0.14
          }
        ],
        "materialDensity": 1.30,
        "materialImageAccessId": "cncAttachments_f5efad7cf8434ff0ab855e734a63f527",
        "materialIntroduce": "2",
        "materialKeyId": 803,
        "materialName": "8228 Resin",
        "materialSort": 1,
        "materialStatus": 1,
        "materialTechnicsId": 1,
        "materialTechnicsName": "SLA(Resin)",
        "materialTitle": "111",
        "materialType": "9000E Resin",
        "materialTypeId": 2,
        "materialUrgentLimit": {
          "nylonMaxCount": 10,
          "nylonMaxHeight": 130,
          "nylonMaxLength": 200,
          "resinMaxHeight": 120,
          "resinMaxLength": 193,
          "resinMaxWeight": 1981
        },
        "modelSize": 1.00,
        "noCraft": false,
        "quotingCoefficient": 1.00,
        "receiveOrderExplain": "2",
        "receiveOrderMax": 1000.00,
        "receiveOrderMaxG": 1000000.00,
        "receiveShopMax": 100000,
        "recommendFlag": false,
        "showColor": false,
        "threeDimensionCraftColorRelationList": [
          {
            "colorBaseAccessId": "8835bb0e2efa47dbb2a708ee63b15d3f",
            "defaultCraftAccessId": "f43a64f0df284159a6d2ecda3cee62de",
            "noCraft": false,
            "threeDimensionCraftAttributeVOList": [
              {
                "craftAccessId": "f6c53f8429404e3ca30a5b0e4cef56b6",
                "craftAttributeAccessIdList": [
                  "7ae10a20bb0843f08f0c5e17580c6176",
                  "8271721b0aee4315843b9c482352a3f2",
                  "41764d0fe13942fcaec551bb37326103"
                ],
                "defaultSelectFlag": false,
                "materialColorAccessId": "d03377ef21904b269dd160b0e3bc331a"
              }
            ]
          }
        ],
        "todayTotalOrderWeight": 9.25,
        "todayTotalOrderWeightG": 9250.00,
        "unableReason": null,
        "volumeAccumulationCoefficient": 1.00,
        "weight": null
      }
      // … more materials …
    ],
    "clearanceParamTreeDTOS": [
      {
        "children": [
          {
            "children": null,
            "label": "Har44d 444 d-ishsk- Enclosure HS Code 80011",
            "sizeX": 10.00,
            "sizeY": 10.00,
            "sizeZ": 10.00,
            "value": "10"
          },
          {
            "children": null,
            "label": "Reader Enclosure 847330 HS Code 8002",
            "sizeX": null,
            "sizeY": null,
            "sizeZ": null,
            "value": "11"
          }
        ],
        "label": "Office Appliance and Accessories",
        "sizeX": null,
        "sizeY": null,
        "sizeZ": null,
        "value": "Office Appliance and Accessories"
      }
      // … more customs categories …
    ]
  }
}
```

---

### `POST /overseas/openapi/tdp/api/calculate` — JLC3DP Calculate Product Price Interface

**Hendley:** `JLCClient.calculate_tdp_price(...)`

Calculate price based on a single item's process: upload file, surface finish, lead time and other parameters to get the calculated price; enter the shipping address to get available shipping methods and their costs.

> Note: `craftShoppingCartDTOList` currently supports only one item.

**Request body (`CalculateRequest`)**

| Field | Type | Required | Description |
|---|---|---|---|
| `craftShoppingCartDTOList` | List&lt;CraftShoppingCartDTO&gt; | no | 3D printing product attributes. Only one item is currently supported (see CraftShoppingCartDTO sub-table). |
| `fileAccessId` | String | yes | File id — the `fileSystemAccessId` returned by the file upload interface. |
| `fileName` | String | yes | File name — the `fileName` returned by the file upload interface. |
| `itemCount` | Integer | yes | Quantity of the product. Minimum value: 1. |
| `itemName` | String | yes | Product name. Can be consistent with the file name. |
| `materialAccessId` | String | yes | Material ID. Must use a selectable material returned from the file upload interface. |
| `materialColorAccessId` | String | yes | Material color id. Must use a selectable material color returned from the file upload interface. |
| `materialDeliveryAccessId` | String | yes | Material delivery date id. Must use a selectable material delivery returned from the file upload interface. |
| `modelAccessId` | String | yes | Model ID. Returned by the file upload interface. |
| `freightMode` | String | no | Shipping method. The pricing interface returns `expressName`. |
| `shippingAddress` | CustomerAddressVO | yes | Customer shipping address (see sub-table). |

**`craftShoppingCartDTOList[]` — CraftShoppingCartDTO**

| Field | Type | Required | Description |
|---|---|---|---|
| `attributes` | List&lt;CraftAttributeShoppingCartDTO&gt; | no | Process attribute. Upload file interface returns (see sub-table). |
| `craftAccessId` | String | yes | Process ID. Upload file interface returns. |

**`craftShoppingCartDTOList[].attributes[]` — CraftAttributeShoppingCartDTO**

| Field | Type | Required | Description |
|---|---|---|---|
| `craftAttributeAccessId` | String | yes | Process attribute ID. Surface finish options are returned by the file upload interface. |
| `customerCraft` | String | no | Additional process information provided by the customer. |
| `resourceUrl` | String | no | The resource URL uploaded by the customer. |

**`shippingAddress` — CustomerAddressVO** (only the fields below are documented in this PDF)

| Field | Type | Required | Description |
|---|---|---|---|
| `country` | String | yes | Country code, such as `CN`. |
| `city` | String | yes | City. |
| `companyName` | String | no | Company name. Individual users can leave this field blank. |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| `errorMessage` | String | Error message. |
| `expressDetailResults` | Array&lt;ExpressDetail&gt; | Selectable shipping information list (see sub-table). |
| `orderTotalWeight` | Number | Total order weight. |
| `tdpCostsVOList` | Array&lt;TdpCost&gt; | 3D printing product information (see sub-table). |
| `tdpTotalLimitWeight` | Number | 3D printing total weight limit. |
| `tdpTotalMoney` | Number | 3D printing total cost. |
| `tdpTotalWeight` | Number | 3D printing total weight. |

**`expressDetailResults[]` — ExpressDetail**

| Field | Type | Description |
|---|---|---|
| `expressDate` | String | Shipping time (e.g. `2-4 business days`). |
| `expressFullName` | String | Express full name. |
| `expressIndex` | Integer | Express sorting. |
| `expressName` | String | Express name (e.g. `dhl`) — supplies `freightMode` in create-order. |
| `expressProposal` | Boolean | Whether to recommend express? |
| `expressRecommend` | Boolean | Whether to select express? |
| `expressRemark` | String | Express configuration remarks. |
| `expressRemark2` | String | Additional express remark. |
| `expressTopName` | String | Express category name. |
| `freightQuotationModel` | Boolean | Whether freight pricing mode is supported? |
| `iossFlag` | Boolean | Whether to support IOSS tax? |
| `maxOrderMoney` | Number | Maximum payment limit for express delivery. |
| `maxWeight` | Number | Maximum weight limit (g). |
| `minDutyFreeMoney` | Number | Minimum duty-free amount. |
| `minWeight` | Number | Minimum weight limit. |
| `prohibitFlag` | Boolean | Is it prohibited? |
| `prohibitText` | String | Prohibition notice. |
| `remoteAreaShippingFee` | Number | Remote area fee. |
| `serviceChargeMoney` | Number | Service charge. |
| `serviceChargeRate` | Number | Service charge rate. |
| `shippingDiscount` | Number | Shipping discount. |
| `shippingMoney` | Number | Shipping cost. |
| `support` | Boolean | Is it supported? |
| `tariff fees` | Number | Tax. (PDF field name literally contains a space: `"tariff fees"`.) |
| `tariffRate` | Number | Tariff rate. |
| `taxIncluded` | Boolean | Is DDP (Delivered Duty Paid) enabled? |
| `taxIncludedMinMoney` | Number | Fixed fee for DDP (Delivered Duty Paid). |
| `taxIncludedMoney` | Number | DDP (Delivered Duty Paid) fee. |
| `useCustomerExpressAccount` | Boolean | Is customer shipping account supported? |
| `weightLimit` | Number | Weight limit (kg). |
| `typeOfTrade` | Integer | Trade type — supplies `typeOfTrade` in create-order. |

**`tdpCostsVOList[]` — TdpCost**

| Field | Type | Description |
|---|---|---|
| `fileAccessId` | String | File uuid. |
| `length` | Number | Length. |
| `limitWeight` | Number | Weight limit. |
| `price` | Number | Price. |
| `unitPrice` | Number | Unit price. |
| `weight` | Number | Weight. |
| `width` | Number | Width. |

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
{
  "fileAccessId": "tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
  "fileName": "RightCover.stl",
  "itemCount": 1,
  "itemName": "RightCover",
  "materialAccessId": "8429f2bab5e7460b8713e8c7fabb622c",
  "materialColorAccessId": "d03377ef21904b269dd160b0e3bc331a",
  "materialDeliveryAccessId": "4b153b77173d4059a1a5073eb06eae5e",
  "modelAccessId": "3f7fe2abea62421d87853dec054d8dfe",
  "freightMode": "dhl",
  "craftShoppingCartDTOList": [
    {
      "craftAccessId": "f6c53f8429404e3ca30a5b0e4cef56b6",
      "attributes": [
        {
          "craftAttributeAccessId": "7ae10a20bb0843f08f0c5e17580c6176",
          "customerCraft": null,
          "resourceUrl": null
        }
      ]
    }
  ],
  "shippingAddress": { "country": "CN", "city": "<city>", "companyName": "" }
}
```
Response:
```json
{
  "code": 200,
  "data": {
    "errorMessage": null,
    "expressDetailResults": [
      {
        "expressDate": "2-4 business days",
        "expressFullName": "DHL Express Worldwide",
        "expressIndex": null,
        "expressName": "dhl",
        "expressProposal": true,
        "expressRecommend": true,
        "expressRemark": "",
        "expressRemark2": null,
        "expressTopName": null,
        "freightQuotationModel": false,
        "iossFlag": true,
        "maxOrderMoney": -1.00,
        "maxWeight": 10000000.00,
        "minDutyFreeMoney": 0,
        "minWeight": 0.00,
        "prohibitFlag": false,
        "prohibitText": null,
        "remoteAreaShippingFee": 0,
        "serviceChargeMoney": 0.27,
        "serviceChargeRate": 0.0500,
        "shippingDiscount": null,
        "shippingMoney": 19.2500,
        "support": true,
        "tariff fees": 5.43,
        "tariffRate": 0.2500,
        "taxIncluded": true,
        "taxIncludedMinMoney": 0.0000,
        "taxIncludedMoney": 5.43,
        "useCustomerExpressAccount": true,
        "weightLimit": null,
        "typeOfTrade": 1
      }
      // … more express options …
    ],
    "orderTotalWeight": 120.00,
    "tdpCostsVOList": [
      {
        "fileAccessId": "tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
        "length": 4.99,
        "limitWeight": 5.19,
        "price": 2.18,
        "unitPrice": 2.17854000000000000000000000000,
        "weight": 0.01,
        "width": 1.84
      }
    ],
    "tdpTotalLimitWeight": 5.19,
    "tdpTotalMoney": 2.18,
    "tdpTotalWeight": 0.13
  }
}
```

---

### `POST /overseas/openapi/tdp/api/order/create` — JLC3DP Create Order Interface

**Hendley:** `JLCClient.create_tdp_order(...)`

Create an order by uploading product model ID, material ID and other related product attributes.

> Note: `craftShoppingCartDTOList` currently supports only one item.
> Note: this PDF's `CustomerAddressVO` ("Shipping Address") documents the fuller 11-field form (vs. the 3 fields shown in the calculate PDF).

**Request body (`CreateOrderRequest`)**

| Field | Type | Required | Description |
|---|---|---|---|
| `craftShoppingCartDTOList` | List&lt;CraftShoppingCartDTO&gt; | no | 3D product attributes. Currently only one can be uploaded (see CraftShoppingCartDTO sub-table). |
| `fileAccessId` | String | yes | File id — the `fileSystemAccessId` returned by the file upload interface. |
| `fileName` | String | yes | File name — the `fileName` returned by the file upload interface. |
| `itemCount` | Integer | yes | Quantity of products. Minimum 1. |
| `itemName` | String | yes | Product name. Can be consistent with the file name. |
| `materialAccessId` | String | yes | Material ID. The file upload interface returns; optional materials must be uploaded. |
| `materialColorAccessId` | String | yes | Material color id. The upload file interface returns; the optional material color must be uploaded. |
| `materialDeliveryAccessId` | String | yes | Material delivery date id. The upload file interface returns; the optional material delivery date must be uploaded. |
| `modelAccessId` | String | yes | Model ID. Upload file interface returns. |
| `customerRemarks` | String | no | Customer notes. Must not exceed 255 characters. |
| `goodsCustomsType` | Integer | yes | Product usage type. Upload file interface returns: `clearanceParamTreeDTOS.children.value`. |
| `freightMode` | String | yes | Shipping method. Pricing interface returns. |
| `typeOfTrade` | Integer | yes | Transaction method. Pricing interface returns. |
| `shippingAddress` | CustomerAddressVO | yes | Customer shipping address (see sub-table). |
| `billingAddress` | CustomerAddressVO | no | Billing address. If `billingUseShippingAddressFlag` is `true`, the billing address is optional and defaults to the shipping address. |
| `billingUseShippingAddressFlag` | Boolean | yes | Is billing address the same as shipping address? `true`/`false`. |
| `batchNum` | String | no | Batch number. Batch number generated, required for order binding. |

**`craftShoppingCartDTOList[]` — CraftShoppingCartDTO**

| Field | Type | Required | Description |
|---|---|---|---|
| `attributes` | List&lt;CraftShoppingCartDTO&gt; | no | Process attributes. Upload file interface returns (see sub-table). |
| `craftAccessId` | String | yes | Process business ID. Upload file interface returns. |

> Note: the PDF literally types `attributes` as `List<CraftShoppingCartDTO>` (reproduced above) — this is almost certainly a PDF typo for `List<CraftAttributeShoppingCartDTO>`, which is the element type described by the sub-table below.

**`craftShoppingCartDTOList[].attributes[]` — CraftAttributeShoppingCartDTO**

| Field | Type | Required | Description |
|---|---|---|---|
| `craftAttributeAccessId` | String | yes | Process attribute business ID. Surface finish attributes derived from the response of the file upload interface. |
| `customerCraft` | String | no | Other process details provided by the customer. |
| `resourceUrl` | String | no | Resource URL uploaded by the customer. |

**`shippingAddress` / `billingAddress` — CustomerAddressVO**

| Field | Type | Required | Description |
|---|---|---|---|
| `country` | String | yes | Country code, such as `CN`. |
| `state` | String | yes | State and Province. |
| `postcode` | String | yes | Post code. |
| `city` | String | yes | City. |
| `taxVat` | String | no | Tax ID. Italy: required for company recipient address. Brazil: required. South Korea, India, Indonesia, Argentina: required for individuals. |
| `street` | String | yes | Street. |
| `street2` | String | no | Detailed address. |
| `companyName` | String | no | Company name. Individual users can leave this field blank. |
| `phone` | String | yes | Telephone number. |
| `firstName` | String | yes | First name. |
| `lastName` | String | yes | Last name. |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| `code` | Integer | Status code. |
| `msg` | String | Prompt message (e.g. `Success`). |
| `data` | String | Return content — the created batch number (e.g. `W2025071809570442`). |

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
{
  "fileAccessId": "tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
  "fileName": "RightCover.stl",
  "itemCount": 1,
  "itemName": "RightCover",
  "materialAccessId": "8429f2bab5e7460b8713e8c7fabb622c",
  "materialColorAccessId": "d03377ef21904b269dd160b0e3bc331a",
  "materialDeliveryAccessId": "4b153b77173d4059a1a5073eb06eae5e",
  "modelAccessId": "3f7fe2abea62421d87853dec054d8dfe",
  "customerRemarks": "",
  "goodsCustomsType": 10,
  "freightMode": "dhl",
  "typeOfTrade": 1,
  "billingUseShippingAddressFlag": true,
  "shippingAddress": {
    "country": "CN",
    "state": "<state>",
    "postcode": "<postcode>",
    "city": "<city>",
    "street": "<street>",
    "firstName": "<firstName>",
    "lastName": "<lastName>",
    "phone": "<phone>"
  },
  "craftShoppingCartDTOList": [
    {
      "craftAccessId": "f6c53f8429404e3ca30a5b0e4cef56b6",
      "attributes": [
        { "craftAttributeAccessId": "7ae10a20bb0843f08f0c5e17580c6176" }
      ]
    }
  ]
}
```
Response:
```json
{
  "code": 200,
  "msg": "Success",
  "data": "W2025071809570442"
}
```

---

### `POST /overseas/openapi/tdp/api/order/list` — JLC3DP Order List Interface

**Hendley:** `JLCClient.list_tdp_orders(...)`

Order list — view successfully created batch orders.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `currentPage` | Integer | yes | Current page number. `0 < currentPage`. |
| `pageRows` | Integer | yes | Items per page. `0 < pageRows`. |
| `searchKey` | String | no | Search keywords — order number, batch number, keyword search. |
| `orderStatisticsType` | Integer | no | Query time range: 1 Last 30 days, 2 Last 6 months, 3 Last 12 months, 4 One year ago. |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| `currentPage` | Integer | Current page. |
| `pageRows` | Integer | Number of rows per page. |
| `size` | Integer | Batch quantity. |
| `pages` | Integer | Total pages. |
| `total` | Integer | Total batches. |
| `list` | Array&lt;Batch&gt; | Batch list (see sub-table). |

**`list[]` — Batch**

| Field | Type | Description |
|---|---|---|
| `batchNum` | String | Batch number. |
| `paidOrderList` | Array&lt;Order&gt; | Paid order list (see Order sub-table). |
| `noPayOrderList` | Array&lt;Order&gt; | Unpaid list (see Order sub-table). |

**`list[].noPayOrderList[]` / `list[].paidOrderList[]` — Order**

| Field | Type | Description |
|---|---|---|
| `allowShare` | Boolean | Is sharing allowed? |
| `askStatus` | Integer | Customer inquiry status. |
| `auditStatus` | Integer | Review status. |
| `batchNum` | String | Batch number. |
| `bookingStatus` | Integer | Forecast status: 0 Not forecasted, 1 Forecasted. |
| `businessProcessType` | Integer | Order process type: 1 Review before payment; 0 Payment before review. |
| `cancelFileAccessId` | String | Cancel file uuid. |
| `cancelFileName` | String | Cancel file name. |
| `cancelRemark` | String | Refund reason. |
| `closeReason` | String | Cancellation reason. |
| `complainReadStatus` | Integer | Complaint reply status: 0 unread; 1 read. |
| `complainStatus` | Integer | Complaint status: 1 Unprocessed, 2 Processing, 3 Completed. |
| `customerCode` | String | Customer number. |
| `decreaseFee` | Number | Discounted fees. |
| `deliveryDate` | Integer | Product delivery time. |
| `deliveryTime` | Long | Delivery time. |
| `deliveryType` | Integer | Delivery type: 1 expedited delivery, 2 normal delivery, 3 other delivery. |
| `extraFee` | Number | Additional fees. |
| `fileAccessId` | String | File uuid. |
| `fileName` | String | File name. |
| `goodsKeyId` | Integer | Product keyId. |
| `goodsTotal` | Number | Total amount of merchandise. |
| `goodsUnitPrice` | Number | Unit price of merchandise. |
| `goodsUsefulness` | String | Product usage. |
| `hasDiscard` | Boolean | Discard the item or not. |
| `isExistComplain` | Integer | Complaint exists? (PDF: "1 exist 1 no" — example value `2`). |
| `materialType` | String | Material type. |
| `orderAccessId` | String | Order UUID. |
| `orderId` | Integer | Order ID. |
| `orderNo` | String | Order number — feeds order-process. |
| `orderStatus` | Integer | Order status: 0 Review failed, 1 Unpaid and unreviewed, 3 Paid and pending review, 30 Waiting for review, 31 Reviewed but not paid, 4 Submitted to factory, 5 Shipped. |
| `orderSupplementMoney` | Number | Supplementary amount. |
| `orderSupplementNum` | String | Transaction number of supplementary record. |
| `orderTotal` | Number | Total order amount. |
| `orderType` | Integer | Order type — 3D printing: 7. |
| `payBindOrder` | String | Support for pay-first-then-review binding (`yes`: supported, `no`: not supported). |
| `payStatus` | String | Payment status (`paySuccess`: payment successful, `unPay`: unpaid). |
| `previewUrl` | String | Thumbnail address. |
| `printRiskFlag` | Boolean | Accept printing risk? 0 Do not accept, 1 Accept. |
| `printRiskOperator` | Integer | Print risk operator: 0 No operation, 1 Customer confirmation, 2 Business confirmation. |
| `problemRemark` | String | Reason for supplementary fees. |
| `problemType` | Integer | Supplementary fee type. |
| `produceWipNumber` | Integer | Production progress quantity (WIP). |
| `produceWipProportion` | Number | Production progress percentage of the order. |
| `productFee` | Number | Merchandise fees. |
| `productInfo` | Object | Product information (see sub-table). |
| `pushStatus` | Integer | Push status: 0 not pushed, 1 success, 2 failed, 3 pushing, 4 paused. |
| `refundStatus` | Integer | Refund status: 10 Confirmed, 20 Refundable, 21 Refunding, 30 Partial refund, 40 Full refund. |
| `replaceFileStatus` | Integer | Replacement status: 0 No replacement needed, 1 Pending replacement, 2 Replacement completed. |
| `replaceReason` | String | Reason for file replacements. |
| `replaceReasonFileFame` | String | Filename of the after-sales file for replacement. (PDF spelling: `replaceReasonFileFame`.) |
| `replaceReasonFileUuid` | String | UUID of the after-sales file for replacement. |
| `resolveList` | Array&lt;Resolve&gt; | Cpp file parsing results (see sub-table). |
| `saleTaxMoney` | Number | US sales tax. |
| `shippingCharge` | Number | Shipping fees. |
| `shoppingCartAccessId` | String | Shopping cart UUID. |
| `tariffChargesMoney` | Number | Tariff fees. |
| `thumbnailUrl` | String | Image. |
| `updateTime` | Long | Update timestamp. |

**`...productInfo` — ProductInfo**

| Field | Type | Description |
|---|---|---|
| `craftInfo` | String | Surface finish information. |
| `deliveryDate` | Integer | Delivery date. |
| `fileName` | String | File name. |
| `goodsCustomsType` | Integer | Product usage type: 1 Toys, 2 Crafts, 3 Parts, 4 Others. |
| `materialAccessId` | String | Material UUID. |
| `materialCode` | String | Material code. |
| `materialColor` | String | Color. |
| `materialName` | String | Material name. |
| `materialTechnicsId` | Integer | Material technology id. |
| `materialTechnicsName` | String | Material technology name. |
| `materialType` | String | Material type. |
| `modelSurfaceArea` | Number | Surface area. |
| `modelVolume` | Number | Volume. |
| `physicalWeight` | Number | Physical weight. |
| `progressName` | String | Process name. |
| `quantity` | Integer | Quantity. |
| `sizeX` | Number | Length. |
| `sizeY` | Number | Width. |
| `sizeZ` | Number | Height. |
| `threeDimensionSurfaceTreatmentVOList` | Array | Surface finish (deprecated). |
| `volumeWeight` | Number | Volume weight. |

**`...resolveList[]` — Resolve**

| Field | Type | Description |
|---|---|---|
| `convertDesc` | String | Conversion description. |
| `convertResultCode` | Integer | Result identification code. |

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
{ "currentPage": 1, "pageRows": 1, "searchKey": "", "orderStatisticsType": 1 }
```
Response:
```json
{
  "code": 200,
  "data": {
    "currentPage": 1,
    "pageRows": 1,
    "size": 0,
    "pages": 106,
    "total": 106,
    "list": [
      {
        "batchNum": "W202310182134757",
        "paidOrderList": [],
        "noPayOrderList": [
          {
            "allowShare": true,
            "askStatus": 0,
            "auditStatus": 0,
            "batchNum": "W202310182134757",
            "bookingStatus": 0,
            "businessProcessType": 0,
            "cancelFileAccessId": "",
            "cancelFileName": "",
            "cancelRemark": null,
            "closeReason": null,
            "complainReadStatus": null,
            "complainStatus": null,
            "customerCode": "5442324A",
            "decreaseFee": 0.00,
            "deliveryDate": 48,
            "deliveryTime": 1697810400000,
            "deliveryType": 2,
            "extraFee": 0.00,
            "fileAccessId": "tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
            "fileName": "RightCover.stl",
            "goodsKeyId": 31812,
            "goodsTotal": 2.18,
            "goodsUnitPrice": null,
            "goodsUsefulness": "",
            "hasDiscard": false,
            "isExistComplain": 2,
            "materialType": "9000E Resin",
            "orderAccessId": "abe445de452845ee870fe0bf3a82f201",
            "orderId": 20422,
            "orderNo": "D2023101834500006",
            "orderStatus": 1,
            "orderSupplementMoney": null,
            "orderSupplementNum": null,
            "orderTotal": 27.13,
            "orderType": 7,
            "payBindOrder": null,
            "payStatus": "unPay",
            "previewUrl": "https://test-tdpapi.jlcpcb.com/weapp/index.html#/model_preview/embedded?modelUrl=https://test-cart.jlcpcb.com/tdpFile/downloadTdpFile?fileAccessId=tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
            "printRiskFlag": false,
            "printRiskOperator": 0,
            "problemRemark": null,
            "problemType": null,
            "produceWipNumber": 0,
            "produceWipProportion": 0.0,
            "productFee": 2.18,
            "productInfo": {
              "craftInfo": "",
              "deliveryDate": 48,
              "fileName": "RightCover.stl",
              "goodsCustomsType": 1,
              "materialAccessId": "8429f2bab5e7460b8713e8c7fabb622c",
              "materialCode": "L8",
              "materialColor": "001",
              "materialName": "8228 Resin",
              "materialTechnicsId": 1,
              "materialTechnicsName": "SLA(Resin)",
              "materialType": "9000E Resin",
              "modelSurfaceArea": 55.73,
              "modelVolume": 3.99,
              "physicalWeight": 5.19,
              "progressName": null,
              "quantity": 1,
              "sizeX": 4.99,
              "sizeY": 1.84,
              "sizeZ": 3.58,
              "threeDimensionSurfaceTreatmentVOList": null,
              "volumeWeight": 10.00
            },
            "pushStatus": 0,
            "refundStatus": null,
            "replaceFileStatus": 0,
            "replaceReason": null,
            "replaceReasonFileFame": null,
            "replaceReasonFileUuid": null,
            "resolveList": [
              {
                "convertDesc": "File errors may occur, the result is subject to final manual review",
                "convertResultCode": -1
              }
            ],
            "saleTaxMoney": 0,
            "shippingCharge": 19.52,
            "shoppingCartAccessId": "2a7dbaec29ce4cb4ad8684886b1858e3",
            "tariffChargesMoney": 5.43,
            "thumbnailUrl": "tdpGoodsFilePreview_424a3fb8aea24441b995782cf0afc73c",
            "updateTime": 1697607369000
          }
          // … more orders …
        ]
      }
      // … more batches …
    ]
  }
}
```

---

### `POST /overseas/openapi/tdp/api/order/detail` — JLC3DP Order Details Interface

**Hendley:** `JLCClient.get_tdp_order_detail(batch_num)`

Query batch order details based on a batch number obtained from the order list.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `batchNum` | String | yes | Batch number — the customer's own batch (returned by the order list interface). |

**Response `data`**

| Field | Type | Description |
|---|---|---|
| `afterCountryName` | String | Payment currency. |
| `batchDeliverStatus` | Integer | Batch delivery status: 1 Marked as pending pre-declaration, 2 Ready for pre-declaration, 3 Pre-declared, 4 Pending customs declaration, 5 Shipped, 6 General cargo completed, 7 Customs declared. |
| `batchNumExpressUuid` | String | UUID of the batch shipping record. |
| `batchProcessNodes` | Array/Object | Batch status nodes: 1 Order submitted, 2 Under review, 3 File processing, 4 In production, 5 Packaging and shipping, 6 In transit. |
| `cncOrderDetailDTOList` | Array | (CNC order detail list; null for 3DP.) |
| `countryName` | String | Country name. |
| `couponsType` | Integer | Discount type: -1 No discount, 0 First order free shipping, 1 Coupon, 2 Universal promo code. |
| `discount` | Number | Discount amount. |
| `exchangeRate` | String | Average exchange rate. |
| `faOrderBatchDTO` | Object | (Order batch DTO; nullable.) |
| `myOrdersRecord` | Object | (Order record; nullable.) |
| `orderDetailNotice` | String | Notification information on the order details page. |
| `pictureColorPath` | String | Auto-weight color image URL. |
| `pictureMonoPath` | String | Auto-weight monochrome image URL. |
| `proxyConsignee` | String | Proxy name. |
| `proxyIdentityCardNumber` | String | ID number of proxy. |
| `proxyPhoneNumber` | String | Phone number of proxy. |
| `recordsDetail` | Object | (Records detail; nullable.) |
| `splitOrderInvoiceAccessIds` | Array | Split order invoice (file upload record AccessId). |
| `taxBillApplyStatus` | Integer | Tax invoice application status: 0 not allowed, 1 allowed, 2 Already applied, 3 Available for download. |
| `taxBillApplyUuid` | String | UUID of tax invoice application. |
| `tdpOrderDetail` | Array&lt;TdpOrderDetail&gt; | 3D printing order details (see sub-table). |

**`tdpOrderDetail[]` — TdpOrderDetail**

| Field | Type | Description |
|---|---|---|
| `advanceChargeMoney` | Number | Order amount. |
| `auditReason` | String | Audit reason. |
| `auditStatus` | Integer | Audit status. |
| `batchNum` | String | Batch number. |
| `businessProcessType` | Integer | Order process type: 1 Review before payment, 0 Payment before review. |
| `cancelTime` | Long | Cancel time. |
| `carriageMoney` | Number | Shipping fee. |
| `createTime` | Long | Creation timestamp. |
| `decreaseFee` | Number | Discounted fee. |
| `deliveryTime` | Long | Shipping time. |
| `dimensionSurfaceTreatmentVOList` | Array | Surface finish (deprecated). |
| `discount` | Number | Discount amount. |
| `discountCarriageMoney` | Number | Discounted shipping fee. |
| `discountOrderMoney` | Number | Discounted merchandise fee. |
| `expressNo` | String | Shipping number. |
| `extraFee` | Number | Additional fee. |
| `freeMoney` | Number | Fee waiver amount. |
| `freightModeName` | String | Shipping method (e.g. `DHL Express Worldwide`). |
| `goods` | Object | Product details (see sub-table). |
| `goodsUsefulness` | String | Product usage. |
| `materialType` | String | Material type. |
| `orderId` | Integer | Order ID. |
| `orderNo` | String | Order number. |
| `orderStatus` | Integer | Order status: 0 Review failed, 1 Unpaid and unreviewed, 3 Paid and pending review, 30 Waiting for review, 31 Reviewed but not paid, 4 Submitted to factory, 5 Shipped. |
| `payStatus` | String | Payment status (`paySuccess`/`unPay`). |
| `paymentMode` | String | Payment method. |
| `paymentTime` | Long | Payment time. |
| `produceTime` | Long | Manufacturing time. |
| `produceWipNumber` | Integer | Manufacturing progress quantity. |
| `refundStatus` | Integer | Refund status: 10 Confirmed, 20 Refundable, 21 Refunding, 30 Partial refund, 40 Full refund. |
| `saleTaxMoney` | Number | Sales tax. |
| `shoppingCartAccessId` | String | Shopping cart UUID. |
| `tariffChargesMoney` | Number | Tariff charges. |
| `taxBillApplyStatus` | Integer | Tax invoice application status: 0 not allowed, 1 allowed, 2 Already applied, 3 available for download. |
| `taxBillApplyUuid` | String | Tax invoice application UUID. |
| `uploadTime` | Long | Upload time. |

**`tdpOrderDetail[].goods` — Goods**

| Field | Type | Description |
|---|---|---|
| `color` | String | Color. |
| `craftInfo` | String | Surface finish information. |
| `customerCode` | String | Customer number. |
| `customerRemarks` | String | Customer remarks. |
| `deliveryDate` | Integer | Delivery time (hours). |
| `fileName` | String | File name. |
| `fileUUID` | String | File uuid. |
| `goodsCustomsType` | Integer | Product usage type: 1 Toy, 2 Craft, 3 Part, 4 Other. |
| `goodsKeyId` | Integer | Product id. |
| `materialCode` | String | Material code. |
| `materialColor` | String | Material color. |
| `materialName` | String | Material name. |
| `materialTechnicsId` | Integer | Material process ID. |
| `materialTechnicsName` | String | Material process name. |
| `modelSurfaceArea` | Number | Surface area. |
| `modelVolume` | Number | Volume. |
| `previewUrl` | String | Thumbnail (signed S3 model URL). |
| `price` | Number | Price. |
| `printRiskFlag` | Boolean | Accept printing risk or not? 0 Do not accept, 1 Accept. |
| `printRiskOperator` | Integer | Accept print risk operator? 0 No operation, 1 Customer confirmation, 2 Business confirmation. |
| `produceCode` | String | Order number. |
| `progressName` | String | Process name. |
| `quantity` | Integer | Quantity. |
| `resolveList` | Array&lt;Resolve&gt; | Cpp file parsing results (`convertDesc`, `convertResultCode`). |
| `sizeX` | Number | Length. |
| `sizeY` | Number | Width. |
| `sizeZ` | Number | Height. |
| `thumbnailUrl` | String | Image URL. |

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
{ "batchNum": "W202310182134757" }
```
Response:
```json
{
  "code": 200,
  "msg": "Success",
  "data": {
    "afterCountryName": null,
    "batchDeliverStatus": 0,
    "batchNumExpressUuid": "f873091fead14e50af5ac80fadc3a588",
    "batchProcessNodes": null,
    "cncOrderDetailDTOList": null,
    "countryName": null,
    "couponsType": null,
    "discount": 0.00,
    "exchangeRate": "7.1",
    "faOrderBatchDTO": null,
    "myOrdersRecord": null,
    "orderDetailNotice": null,
    "pictureColorPath": null,
    "pictureMonoPath": null,
    "proxyConsignee": "",
    "proxyIdentityCardNumber": "",
    "proxyPhoneNumber": "",
    "recordsDetail": null,
    "splitOrderInvoiceAccessIds": [],
    "taxBillApplyStatus": 0,
    "taxBillApplyUuid": null,
    "tdpOrderDetail": [
      {
        "advanceChargeMoney": 2.18,
        "auditReason": null,
        "auditStatus": 0,
        "batchNum": "W202310182134757",
        "businessProcessType": 0,
        "cancelTime": null,
        "carriageMoney": 19.52,
        "createTime": 1697636059000,
        "decreaseFee": 0.00,
        "deliveryTime": null,
        "dimensionSurfaceTreatmentVOList": null,
        "discount": null,
        "discountCarriageMoney": null,
        "discountOrderMoney": null,
        "expressNo": null,
        "extraFee": 0.00,
        "freeMoney": 0,
        "freightModeName": "DHL Express Worldwide",
        "goods": {
          "color": null,
          "craftInfo": "",
          "customerCode": "5442324A",
          "customerRemarks": "",
          "deliveryDate": 48,
          "fileName": "RightCover.stl",
          "fileUUID": "tdpGoodsFile_5156b6d49e464efe91301f8ad135df60",
          "goodsCustomsType": 1,
          "goodsKeyId": 31812,
          "materialCode": "L8",
          "materialColor": "white",
          "materialName": "8228 Resin",
          "materialTechnicsId": 1,
          "materialTechnicsName": "SLA(Resin)",
          "modelSurfaceArea": 55.73,
          "modelVolume": 3.99,
          "previewUrl": "https://test-tdpapi.jlcpcb.com/weapp/index.html#/model_preview/embedded?modelUrl=https://jlc-uat-tdp.s3.eu-central-1.amazonaws.com/tdpFile/...&X-Amz-Signature=af217ac7...",
          "price": 2.1785,
          "printRiskFlag": false,
          "printRiskOperator": 0,
          "produceCode": "D2023101834500006",
          "progressName": null,
          "quantity": 1,
          "resolveList": [
            {
              "convertDesc": "File errors may occur, the result is subject to final manual review",
              "convertResultCode": -1
            }
          ],
          "sizeX": 4.99,
          "sizeY": 1.84,
          "sizeZ": 3.58,
          "thumbnailUrl": "tdpGoodsFilePreview_424a3fb8aea24441b995782cf0afc73c"
        },
        "goodsUsefulness": "",
        "materialType": "9000E Resin",
        "orderId": 20422,
        "orderNo": "D2023101834500006",
        "orderStatus": 1,
        "payStatus": "unPay",
        "paymentMode": "",
        "paymentTime": null,
        "produceTime": null,
        "produceWipNumber": 0,
        "refundStatus": null,
        "saleTaxMoney": 0,
        "shoppingCartAccessId": "2a7dbaec29ce4cb4ad8684886b1858e3",
        "tariffChargesMoney": 5.43,
        "taxBillApplyStatus": null,
        "taxBillApplyUuid": null,
        "uploadTime": 1697607369000
      }
      // … more order details …
    ]
  }
}
```

---

### `POST /overseas/openapi/tdp/api/order/process` — JLC3DP Order Progress Interface

**Hendley:** `JLCClient.get_tdp_order_process(order_no)`

Order Manufacturing Progress — query the manufacturing progress of an order based on the order number returned from the order list.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `orderNo` | String | yes | Order number — the customer order number (returned by the order list interface). |

**Response `data`**

> Note: `data` is an **array** of progress-node objects (not an object).

| Field | Type | Description |
|---|---|---|
| `createTime` | Long | Creation time. |
| `endTime` | Long | End time. |
| `goodsKeyId` | Integer | Product id. |
| `materialType` | String | Material type. |
| `materialTypeId` | Integer | Material type id. |
| `modelName` | String | Model name. |
| `orderNo` | String | Order number. |
| `processCode` | String | Manufacturing number (process code, e.g. `dymx`, `qzc`, `qx`, `hgh`, `bdm`, `qc`). |
| `progress` | Integer | Manufacturing progress number. |
| `progressAccessId` | String | Manufacturing progress business id. |
| `progressCnName` | String | Chinese name of progress. |
| `progressName` | String | English name of the progress. |

Observed progress sequence in the example: 0 Data Processing → 1 Printing → 2 Support Removal → 3 Rinsing → 4 Post-Curing → 5 Sanding-No → 6 QC.

**Errors**

| Code | Meaning |
|---|---|
| 200 | 200 only documented (no error table in PDF). |

**Example**

Request:
```json
{ "orderNo": "D2023092752500058" }
```
Response:
```json
{
  "code": 200,
  "msg": "Success",
  "data": [
    {
      "createTime": 1695812369000,
      "endTime": 1695812469000,
      "goodsKeyId": 337734,
      "materialType": "Resin",
      "materialTypeId": 2,
      "modelName": "CoD_keychain.stl",
      "orderNo": "D2023092752500058",
      "processCode": null,
      "progress": 0,
      "progressAccessId": null,
      "progressCnName": "Data processing",
      "progressName": "Data Processing"
    },
    {
      "createTime": 1695812368000,
      "endTime": 1695812510000,
      "goodsKeyId": 337734,
      "materialType": "Resin",
      "materialTypeId": 2,
      "modelName": "CoD_keychain.stl",
      "orderNo": "D2023092752500058",
      "processCode": "dymx",
      "progress": 1,
      "progressAccessId": null,
      "progressCnName": "Print model",
      "progressName": "Printing"
    }
    // … more progress nodes: qzc/Support Removal(2), qx/Rinsing(3),
    //     hgh/Post-Curing(4), bdm/Sanding-No(5), qc/QC(6) …
  ]
}
```
