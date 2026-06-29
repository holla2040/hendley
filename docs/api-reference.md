# JLCPCB OpenAPI — Reference (reverse-engineered from the official Java SDK)

This document captures the JLCPCB OpenAPI contract, cross-checked from three
sources: the official Java SDK jars (`sdk/`), the console "View Docs" PDFs, and —
for the component routes — the **live API**. It is the source of truth for the
Python reimplementation in `src/henley/`.

- **Endpoint (overseas/global):** `https://open.jlcpcb.com` (the default in
  `config.py`; also what every official PDF uses). `api.jlcpcb.com` is the
  developer portal/console, *not* the API host. The Java SDK's baked-in default
  is `https://openapi.jlc.com` (China).
- **All JSON routes are `POST`** (even getter-shaped names); file uploads are
  `POST multipart/form-data`.
- **Where the sources disagree, the live API wins, not the PDF.** Two PDFs are
  demonstrably wrong vs. the live server: private-stock paging is `currentPage`
  (the PDF's `pageNum` is silently ignored → always page 1), and `data` for the
  component routes is a bare list, not the wrapper objects the PDFs show.

## Authentication — the `JOP` scheme

Each request carries an `Authorization` header built as follows
(`com.jlc.openapi.core.client.auth.authorization.SignAuthorization`):

```
string_to_sign = METHOD + "\n"
               + CANONICAL_URI + "\n"        # raw path, plus "?"+rawQuery if present
               + TIMESTAMP + "\n"            # str(int(epoch_seconds))
               + NONCE + "\n"                # 32-char random token
               + PAYLOAD + "\n"              # exact request body; "" for GET

signature = Base64( HMAC_SHA256(secret_key, string_to_sign) )

Authorization: JOP appid="<AppID>",accesskey="<Accesskey>",
               timestamp="<ts>",nonce="<nonce>",signature="<signature>"
```

Defaults from the SDK (`AuthProfile.Builder`): authenticator `JOP`
(scheme is literally `JOP`, no algorithm suffix), sign algorithm `HMAC_SHA256`.
The `secret_key` is the `.keys` `SecretKey`; `accesskey` is the `.keys`
`Accesskey`.

Other algorithms exist but are not the default: `HmacSHA1`, `SHA256withRSA`
(`RSA_SHA256`, signs with the RSA private key), `HMAC-SM3`.

Standard headers added by the SDK on every JSON call: `Authorization`,
`Content-Type: application/json`, `Accept: application/json`, `Accept-Language`,
`User-Agent`.

### Field tokenization (privacy) — orders only

For order placement the SDK can RSA-encrypt sensitive fields (e.g. shipping
address) with the public key in `.keys` ("Tokenization Key RSA"). Algorithm is
RSA (PKCS#1 v1.5) or SM2. **Not needed for read-only parts queries.**

## Serialization

`toJSON()` serializes Java fields by their **camelCase names** (a `@NameInMap`
annotation can override, but the component VOs don't use it). **Null fields are
omitted.** Nested objects/lists are serialized recursively.

## Response envelope

Responses wrap payloads as `{ code, message, data }` (success code `200`).
`data` is the per-endpoint structure below.

---

## Component (parts inventory) endpoints

### `POST /overseas/openapi/component/getComponentLibraryList`
Browse the assembly (SMT) component library, cursor-paginated.

Request: `{ "pageSize": int = 30, "lastKey": string|null }`
(`ComponentListRequest` uses `currentPage`/`pageSize`; `GetComponentLibraryRequest`
uses `pageSize`/`lastKey` — same URI, cursor form preferred.)

Response `data` (`ComponentLibraryResponseVO`):
- `componentLibraryInfoVOS`: list of
  - `componentCode`: string  (JLC code, e.g. `C2040`)
  - `componentModel`: string  (manufacturer part / model)
  - `componentSpecification`: string
- `lastKey`: string  (cursor for the next page)

### `POST /overseas/openapi/component/getComponentDetailByCode`
Full detail for specific component codes.

Request: `{ "componentCodes": [string, ...] }`

Response `data`: list of `ComponentDetailResponseVO`:
- `componentCode`: string
- `componentModel`: string
- `componentSpecification`: string
- `firstTypeName`: string  (top-level category)
- `secondTypeName`: string  (sub-category)
- `libraryType`: string  (e.g. base/extended)
- `description`: string
- `datasheetUrl`: string
- `solderJointCount`: int
- `priceRanges`: list of `{ startQuantity: long, endQuantity: long, unitPrice: decimal }`
- `stockCount`: int
- `parameters`: list of `{ parameterName: string, parameterValue: string }`
- `assemblyComponentFlag`: bool
- `eccnCode`: string
- `rohsFlag`: bool
- `dataManualUrl`, `dataManualOfficialLink`, `dataManualFileAccessId`: string
  (present in the live response; the SDK's `lcscComponentId` is **not** returned)

`data` is the bare list above (the PDF's `componentDetailResponseVOList` wrapper
is not what the live server sends). Up to 1000 codes per request.

### `POST /overseas/openapi/component/getComponentInfos`
Bulk component info stream (cursor via `lastKey`).

Request: `{ "lastKey": string|null }`

Response `data` (`GetComponentInfoData`):
- `componentInfos`: list of `ComponentInfoVO`:
  - `lcscPart`: string
  - `firstCategory`, `secondCategory`: string
  - `mfrPart`: string
  - `packageInfo`: string
  - `solderJoint`: string
  - `manufacturer`: string
  - `libraryType`: string
  - `description`: string
  - `datasheet`: string
  - `price`: string
  - `stock`: int
- `lastKey`: string

### `POST /overseas/openapi/component/getPrivateComponentLibrary`
Your private/consigned inventory held at JLCPCB.

Request: `{ "currentPage": int = 1, "pageSize": int = 100 }`
(Use `currentPage`, **not** the PDF's `pageNum` — the server ignores `pageNum`.
Live default `pageSize` is 100.)

Response `data`: bare list of `ComponentPrivateStockVO`:
- `componentModel`, `componentSpecification`, `componentCode`: string
- `jlcpcbParts`: int
- `globalSourcingParts`: int
- `consignedParts`: int
- `idleStock`: int

---

## PCB order endpoints

Wrapped in `client.py` (PCB methods). **Reverse-engineered** from the SDK jars +
console PDFs — only the two uploads are live-verified; the JSON order routes are
not exercised here (they price/place real orders). They reuse the same signed
`_post` plumbing proven by the component routes, so signing/transport is sound;
the request field names come from the SDK request classes.

**File uploads** (`upload_gerber`, `upload_blind_via_hole_img`) are
`POST multipart/form-data` with a `file` part + a `fileName` field. They sign an
**empty payload** (the file is not in the string-to-sign) — *verified live*; the
PDFs' `Content-Type: application/json` header note is boilerplate and wrong.
Response `data` is the file-identifier string.

- `POST /overseas/openapi/pcb/uploadGerber` — Gerber archive (rar/zip).
  Errors: 2001 file-verification, 2002 size.
- `POST /overseas/openapi/pcb/uploadBlindViaHoleImg` — blind/slot image (PNG/JPG,
  ≤10 MB). Errors: 2006 empty, 2001 format, 2002 size, 2007 upload, 2008
  risk-control, 1003 system.
- `POST /overseas/openapi/pcb/getImpedanceTemplateSettingList` — stack-up
  templates (`stencilLayer, stencilPly, cuprumThickness, insideCuprumThickness,
  plateType, delamination`) → rows carrying `impedanceTemplateCode`.
- `POST /overseas/openapi/pcb/calculate` — online quote (`GetOnlineCalculatePriceRequest`:
  `orderType, fileKey, achieveDate, pcbParam, smtStencilParam, country, postCode,
  city, batchNum, shippingMethod`).
- `POST /overseas/openapi/pcb/audit/get` — DFM pre-review (`key`, `language`).
- `POST /overseas/openapi/pcb/order/detail` — order info by `batchNum`.
- `POST /overseas/openapi/pcb/wip/get` — production progress by `orderUUID`.
- `POST /overseas/openapi/pcb/create` — place order (`PcbCreateOrderRequest`:
  `orderType, fileKey, shippingAddress, taxOrVATNumber, billingAddressFlag,
  shippingMethod, pcbParam, smtStencilParam, achieveDate, batchNum,
  billingAddress`; `OrderAddressData` fields are RSA-tokenized by the SDK — not
  handled here). Response `data`: `{orderId, orderType, orderDate, batchNum}`.
- `POST /overseas/openapi/pcb/getSteelPriceConfig` — stencil price config. **No
  official PDF**; path is jar-only and the request-body shape is unconfirmed
  (sent empty). (The SDK route is POST, not the `GET` an earlier note guessed.)

The large `pcbParam` (`PcbOrderCraftData`, ~40 fields) and `smtStencilParam`
(`SteelOrderCraftData`) objects are passed through as dicts; their authoritative
field names are the camelCase getters of the SDK request classes under
`pcb/request/data/` (e.g. `layer, width, length, qty, thickness, pcbColor,
surfaceFinish, copperWeight, impedanceTemplateCode, viaCovering, panelFlag,
panelByJLCPCB_X/_Y, serviceConfigVos, pcbBlindViaHoleInfoDTOList, …`). Note the
SDK spells the impedance response list `iaminationList` (typo baked into the API).

## TDP (3D-printing / JLC3DP) order endpoints

Wrapped in `client.py` (TDP methods). Reverse-engineered; not exercised here.
All `POST`. Workflow is an ordered pipeline:

1. `POST /overseas/openapi/tdp/api/upload` — model file
   (stl/stp/step/obj/3mf/rar/zip, ≤80 MB), same multipart+empty-payload signing
   as PCB uploads. The file id is returned in the envelope **`message`** (not
   `data`), with the `successful` flag.
2. `POST /overseas/openapi/tdp/api/file/result` — poll parse results by
   `fileAccessId`; repeat until `data.finishFlag`. Returns model dimensions + the
   selectable material/color/delivery option ids.
3. `POST /overseas/openapi/tdp/api/calculate` — price one item (`fileAccessId,
   fileName, itemCount, itemName, materialAccessId, materialColorAccessId,
   materialDeliveryAccessId, modelAccessId, shippingAddress`, …). Returns price +
   `expressDetailResults` (supplying `freightMode`/`typeOfTrade`).
4. `POST /overseas/openapi/tdp/api/order/create` — place order (calculate's
   fields **plus** `goodsCustomsType, freightMode, typeOfTrade,
   billingUseShippingAddressFlag, billingAddress, batchNum`). Response `data` =
   batch-number string.
5. Tracking: `POST /overseas/openapi/tdp/api/order/list` (`currentPage, pageRows,
   searchKey, orderStatisticsType`), `POST /overseas/openapi/tdp/api/order/detail`
   (`batchNum`), `POST /overseas/openapi/tdp/api/order/process` (`orderNo`).

**Envelope variants:** most routes use `{code, success, message, data}`, but TDP
`upload` uses `successful` + id-in-`message`, and some TDP routes use `msg`
instead of `message`. `client._success`/`_unwrap` handle all three.

See the SDK request classes under `pcb/request/` and `tdp/request/` for exact,
authoritative field lists of the order bodies.
