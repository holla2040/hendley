"""HTTP client for the JLCPCB OpenAPI.

Covers every endpoint documented in the official console "View Docs" PDFs:

- **Component (parts inventory):** library list, detail-by-code, info stream,
  private/consigned stock.
- **PCB:** Gerber upload, blind-via/slot-image upload, impedance templates,
  online quote, pre-review (audit), order create, order detail, production
  progress (WIP), and steel/stencil price config.
- **TDP (3D printing):** model-file upload, parse-result polling, price
  calculate, order create, and order list / detail / process.

Source-of-truth notes
----------------------
The four **component** endpoints are verified against the live API. The **PCB**
and **TDP** routes place/price real orders and have *not* been exercised
end-to-end here; their paths, request field names, and transport are
reverse-engineered from the official Java SDK jars (``sdk/``) cross-checked with
the console PDFs. Request field names follow the SDK request classes / PDF
examples. Where they disagree, the **live API** is the tiebreaker, not the PDF:
e.g. the PDF documents private-stock paging as ``pageNum``, but the server only
honours the SDK's ``currentPage`` (``pageNum`` is silently ignored — verified
empirically), and the component ``data`` payloads are bare lists, not the wrapper
objects the PDFs show.

The big PCB/TDP order bodies (``pcbParam``, ``smtStencilParam``,
``shippingAddress``, craft carts, …) are passed through as plain dicts mirroring
the JSON — see ``docs/api-reference.md`` for the full nested field schemas. This
keeps the client correct-by-construction (it forwards exactly what you supply)
rather than freezing ~40-field contracts we can't exercise.
"""

from __future__ import annotations

import json
import os
import platform
from typing import Any, Iterator
from urllib.parse import urlsplit

import requests

from . import auth
from .config import Settings, load_settings

_USER_AGENT = f"hendley/0.1.0 (python {platform.python_version()})"


class JLCError(RuntimeError):
    """Raised when the API returns a non-success envelope."""

    def __init__(self, code: Any, message: str, payload: Any = None):
        super().__init__(f"JLC API error [{code}]: {message}")
        self.code = code
        self.message = message
        self.payload = payload


class JLCClient:
    """Thin signed client for the JLCPCB OpenAPI.

    JSON routes go through :meth:`_post`; file-upload routes go through
    :meth:`_upload` (``multipart/form-data``, signed with an empty payload).
    """

    def __init__(self, settings: Settings | None = None, *, timeout: float = 30.0):
        self.settings = settings or load_settings()
        self.timeout = timeout
        self._session = requests.Session()

    # -- low level -------------------------------------------------------
    def _url(self, uri: str) -> str:
        return self.settings.endpoint + uri

    def _auth_headers(self, method: str, uri: str, payload: str, *, json_ct: bool = False) -> dict[str, str]:
        cred = self.settings.credentials
        canonical_uri = urlsplit(self._url(uri)).path  # POST bodies carry no query string
        header = auth.authorization_header(
            app_id=cred.app_id,
            access_key=cred.access_key,
            secret_key=cred.secret_key,
            method=method,
            canonical_uri=canonical_uri,
            payload=payload,
        )
        headers = {"Authorization": header, "Accept": "application/json", "User-Agent": _USER_AGENT}
        if json_ct:
            headers["Content-Type"] = "application/json"
        return headers

    def _envelope(self, resp: requests.Response) -> Any:
        """Parse the JSON envelope, even on HTTP 4xx (JLC returns it anyway)."""
        try:
            return resp.json()
        except ValueError:
            resp.raise_for_status()
            raise

    def _post(self, uri: str, body: dict[str, Any] | None = None) -> Any:
        """Sign and POST a JSON request, returning the unwrapped ``data`` payload."""
        # Omit null fields, matching the Java SDK's toJSON() behaviour.
        clean = {k: v for k, v in (body or {}).items() if v is not None}
        payload = json.dumps(clean, separators=(",", ":"))
        headers = self._auth_headers("POST", uri, payload, json_ct=True)
        resp = self._session.post(
            self._url(uri), data=payload.encode("utf-8"), headers=headers, timeout=self.timeout
        )
        return _unwrap(self._envelope(resp))

    def _upload(self, uri: str, file: Any, file_name: str | None = None, *, field: str = "file") -> Any:
        """Sign and POST a ``multipart/form-data`` file upload, returning the raw envelope.

        ``file`` may be a path, raw ``bytes``, or a binary file-like object. Uploads
        sign an **empty payload** (like a GET) — the file is not part of the
        string-to-sign (verified against the live API). The envelope is returned
        raw because PCB uploads carry the id in ``data`` while TDP upload uses
        ``message``.
        """
        blob, name = _read_file(file, file_name)
        headers = self._auth_headers("POST", uri, "")
        resp = self._session.post(
            self._url(uri),
            files={field: (name, blob, "application/octet-stream")},
            data={"fileName": name},
            headers=headers,
            timeout=self.timeout,
        )
        return self._envelope(resp)

    # ====================================================================
    # Component (parts inventory) endpoints  [verified against live API]
    # ====================================================================
    def get_component_library_list(self, *, page_size: int = 30, last_key: str | None = None) -> dict:
        """One page of the JLC assembly component library (cursor-paginated).

        Returns ``{"componentLibraryInfoVOS": [...], "lastKey": str}``.
        """
        return self._post(
            "/overseas/openapi/component/getComponentLibraryList",
            {"pageSize": page_size, "lastKey": last_key},
        )

    def get_component_detail_by_code(self, codes: list[str]) -> list[dict]:
        """Full detail (price tiers, stock, parameters, datasheet) by component code.

        ``codes`` supports up to 1000 codes per call. The live API returns ``data``
        as the list of detail objects directly — the PDF's
        ``componentDetailResponseVOList`` wrapper is not what the server sends
        (verified against the live API).
        """
        return self._post(
            "/overseas/openapi/component/getComponentDetailByCode",
            {"componentCodes": list(codes)},
        ) or []

    def get_component_infos(self, *, last_key: str | None = None) -> dict:
        """Bulk component info stream (LCSC part, package, stock, price).

        Returns ``{"componentInfos": [...], "lastKey": str}`` (cursor via ``lastKey``).
        """
        return self._post(
            "/overseas/openapi/component/getComponentInfos",
            {"lastKey": last_key},
        )

    def get_private_component_library(self, *, current_page: int = 1, page_size: int = 100) -> list[dict]:
        """Your private/consigned inventory held at JLCPCB (offset-paginated).

        Returns the list of stock rows for the page; ``data`` is a bare list (the
        PDF's ``{list, pageNum, total}`` wrapper is not what the server sends).
        Paginate with ``current_page`` (1-based): despite the official PDF
        documenting ``pageNum``, the live API only honours ``currentPage`` —
        verified empirically (``pageNum`` is ignored and always returns page 1).
        """
        return self._post(
            "/overseas/openapi/component/getPrivateComponentLibrary",
            {"currentPage": current_page, "pageSize": page_size},
        ) or []

    # -- component convenience iterators ---------------------------------
    def iter_component_library(self, *, page_size: int = 100) -> Iterator[dict]:
        """Iterate the entire assembly library, following the ``lastKey`` cursor."""
        last_key = None
        while True:
            data = self.get_component_library_list(page_size=page_size, last_key=last_key)
            rows = (data or {}).get("componentLibraryInfoVOS") or []
            for row in rows:
                yield row
            last_key = (data or {}).get("lastKey")
            if not last_key or not rows:
                return

    def iter_component_infos(self) -> Iterator[dict]:
        """Iterate the full component info stream, following the ``lastKey`` cursor."""
        last_key = None
        while True:
            data = self.get_component_infos(last_key=last_key) or {}
            rows = data.get("componentInfos") or []
            for row in rows:
                yield row
            last_key = data.get("lastKey")
            if not last_key or not rows:
                return

    def iter_private_component_library(self, *, page_size: int = 100) -> Iterator[dict]:
        """Iterate all private/consigned stock rows, paging by ``currentPage``.

        The response is a bare list with no total, so paging stops on the first
        short (or empty) page.
        """
        page = 1
        while True:
            rows = self.get_private_component_library(current_page=page, page_size=page_size) or []
            for row in rows:
                yield row
            if len(rows) < page_size:
                return
            page += 1

    # ====================================================================
    # PCB order endpoints  [reverse-engineered: SDK jars + console PDFs]
    # ====================================================================
    def upload_gerber(self, file: Any, *, file_name: str | None = None) -> str | None:
        """Upload a Gerber archive (rar/zip). Returns the file identifier string."""
        return _unwrap(self._upload("/overseas/openapi/pcb/uploadGerber", file, file_name))

    def upload_blind_via_hole_img(self, file: Any, *, file_name: str | None = None) -> str | None:
        """Upload a blind/buried-via slot image (PNG/JPG, ≤10 MB). Returns the file id."""
        return _unwrap(self._upload("/overseas/openapi/pcb/uploadBlindViaHoleImg", file, file_name))

    def get_impedance_template_setting_list(
        self,
        *,
        stencil_layer: int,
        stencil_ply: float,
        cuprum_thickness: float,
        inside_cuprum_thickness: float,
        plate_type: int,
        delamination: bool | None = None,
    ) -> list[dict]:
        """List impedance/stack-up templates for a board spec.

        ``plate_type``: 1 FR4, 2 Aluminum, 4 Copper Core, 5 Rogers, 6 PTFE Teflon,
        7 Flex. Each row carries an ``impedanceTemplateCode`` to feed into
        :meth:`calculate_pcb_price` / :meth:`create_pcb_order`.
        """
        return self._post(
            "/overseas/openapi/pcb/getImpedanceTemplateSettingList",
            {
                "stencilLayer": stencil_layer,
                "stencilPly": stencil_ply,
                "cuprumThickness": cuprum_thickness,
                "insideCuprumThickness": inside_cuprum_thickness,
                "plateType": plate_type,
                "delamination": delamination,
            },
        )

    def calculate_pcb_price(
        self,
        *,
        order_type: int,
        file_key: str,
        achieve_date: int,
        pcb_param: dict | None = None,
        smt_stencil_param: dict | None = None,
        country: str | None = None,
        post_code: str | None = None,
        city: str | None = None,
        batch_num: str | None = None,
        shipping_method: str | None = None,
    ) -> dict:
        """Online quotation for a PCB / stencil order.

        ``order_type``: 1 PCB, 2 PCB+Stencil, 3 Stencil. ``file_key`` is the
        Gerber id from :meth:`upload_gerber`. ``pcb_param``/``smt_stencil_param``
        are the ``PcbOrderCraftData`` / ``SteelOrderCraftData`` dicts — see
        ``docs/api-reference.md`` for their full field lists.
        """
        return self._post(
            "/overseas/openapi/pcb/calculate",
            {
                "orderType": order_type,
                "fileKey": file_key,
                "achieveDate": achieve_date,
                "pcbParam": pcb_param,
                "smtStencilParam": smt_stencil_param,
                "country": country,
                "postCode": post_code,
                "city": city,
                "batchNum": batch_num,
                "shippingMethod": shipping_method,
            },
        )

    def get_pcb_audit_info(self, key: str, *, language: int | None = None) -> dict:
        """PCB pre-review (DFM) results for an uploaded Gerber.

        ``key`` is the Gerber file id. ``language``: 0 EN, 1 KO, 2 JA, 3 TR.
        """
        return self._post(
            "/overseas/openapi/pcb/audit/get",
            {"key": key, "language": language},
        )

    def get_order_detail_by_batch_num(self, batch_num: str) -> dict:
        """Order information (addresses, items, totals) for a batch number."""
        return self._post(
            "/overseas/openapi/pcb/order/detail",
            {"batchNum": batch_num},
        )

    def get_pcb_wip_process(self, order_uuid: str) -> list[dict]:
        """Production-progress (WIP) timeline for a PCB order UUID."""
        return self._post(
            "/overseas/openapi/pcb/wip/get",
            {"orderUUID": order_uuid},
        )

    def create_pcb_order(
        self,
        *,
        order_type: int,
        file_key: str,
        shipping_address: dict,
        tax_or_vat_number: str,
        billing_address_flag: bool,
        shipping_method: str,
        pcb_param: dict | None = None,
        smt_stencil_param: dict | None = None,
        achieve_date: int | None = None,
        batch_num: str | None = None,
        billing_address: dict | None = None,
    ) -> dict:
        """Place a PCB / stencil order. Returns ``{orderId, orderType, orderDate, batchNum}``.

        ``shipping_address`` / ``billing_address`` are ``OrderAddressData`` dicts
        (the SDK RSA-tokenizes address fields — not handled here). ``batch_num``
        empty ⇒ combine-order. ``billing_address`` is required when
        ``billing_address_flag`` is true. See ``docs/api-reference.md`` for the
        full ``OrderAddressData`` / craft-data schemas.
        """
        return self._post(
            "/overseas/openapi/pcb/create",
            {
                "orderType": order_type,
                "fileKey": file_key,
                "shippingAddress": shipping_address,
                "taxOrVATNumber": tax_or_vat_number,
                "billingAddressFlag": billing_address_flag,
                "shippingMethod": shipping_method,
                "pcbParam": pcb_param,
                "smtStencilParam": smt_stencil_param,
                "achieveDate": achieve_date,
                "batchNum": batch_num,
                "billingAddress": billing_address,
            },
        )

    def get_steel_price_config(self, body: dict | None = None) -> Any:
        """Stencil (steel) price config. No official PDF exists for this route; the
        path is jar-derived and the request body shape is unconfirmed (empty by
        default).
        """
        return self._post("/overseas/openapi/pcb/getSteelPriceConfig", body or {})

    # ====================================================================
    # TDP (3D printing) endpoints  [reverse-engineered: SDK jars + PDFs]
    #
    # Workflow: upload_tdp_file -> get_tdp_file_result (poll until finishFlag) ->
    # calculate_tdp_price -> create_tdp_order -> list/detail/process tracking.
    # ====================================================================
    def upload_tdp_file(self, file: Any, *, file_name: str | None = None) -> str | None:
        """Upload a 3D model (stl/stp/step/obj/3mf/rar/zip, ≤80 MB) and start parsing.

        The file id is returned in the envelope ``message`` (not ``data``); feed it
        to :meth:`get_tdp_file_result` as ``fileAccessId``.
        """
        env = self._upload("/overseas/openapi/tdp/api/upload", file, file_name)
        _check(env)
        return (env or {}).get("message")

    def get_tdp_file_result(self, file_access_id: str) -> dict:
        """Poll model-parse results. Repeat until ``data.finishFlag`` is true.

        Returns model dimensions and the selectable material/color/delivery option
        lists whose ids feed :meth:`calculate_tdp_price`.
        """
        return self._post(
            "/overseas/openapi/tdp/api/file/result",
            {"fileAccessId": file_access_id},
        )

    def calculate_tdp_price(
        self,
        *,
        file_access_id: str,
        file_name: str,
        item_count: int,
        item_name: str,
        material_access_id: str,
        material_color_access_id: str,
        material_delivery_access_id: str,
        model_access_id: str,
        shipping_address: dict,
        freight_mode: str | None = None,
        goods_customs_type: int | None = None,
        goods_usefulness: str | None = None,
        item_price: float | None = None,
        customer_remarks: str | None = None,
        surface_treatment_process: Any | None = None,
        craft_shopping_cart_dto_list: list | None = None,
    ) -> dict:
        """Price a 3D-printing item and return shipping options for an address.

        The ``*_access_id`` values come from :meth:`get_tdp_file_result`.
        ``shipping_address`` is a ``CustomerAddress`` dict. The response
        ``expressDetailResults`` supply ``freightMode``/``typeOfTrade`` for
        :meth:`create_tdp_order`.
        """
        return self._post(
            "/overseas/openapi/tdp/api/calculate",
            {
                "fileAccessId": file_access_id,
                "fileName": file_name,
                "itemCount": item_count,
                "itemName": item_name,
                "materialAccessId": material_access_id,
                "materialColorAccessId": material_color_access_id,
                "materialDeliveryAccessId": material_delivery_access_id,
                "modelAccessId": model_access_id,
                "shippingAddress": shipping_address,
                "freightMode": freight_mode,
                "goodsCustomsType": goods_customs_type,
                "goodsUsefulness": goods_usefulness,
                "itemPrice": item_price,
                "customerRemarks": customer_remarks,
                "surfaceTreatmentProcess": surface_treatment_process,
                "craftShoppingCartDTOList": craft_shopping_cart_dto_list,
            },
        )

    def create_tdp_order(
        self,
        *,
        file_access_id: str,
        file_name: str,
        item_count: int,
        item_name: str,
        material_access_id: str,
        material_color_access_id: str,
        material_delivery_access_id: str,
        model_access_id: str,
        shipping_address: dict,
        goods_customs_type: int,
        freight_mode: str,
        type_of_trade: int,
        billing_use_shipping_address_flag: bool,
        billing_address: dict | None = None,
        batch_num: str | None = None,
        customer_remarks: str | None = None,
        goods_usefulness: str | None = None,
        item_price: float | None = None,
        surface_treatment_process: Any | None = None,
        craft_shopping_cart_dto_list: list | None = None,
    ) -> dict:
        """Place a 3D-printing order. Returns the batch-number string in ``data``.

        ``freight_mode`` and ``type_of_trade`` come from
        :meth:`calculate_tdp_price`'s ``expressDetailResults``;
        ``goods_customs_type`` from the file-result customs cascade.
        """
        return self._post(
            "/overseas/openapi/tdp/api/order/create",
            {
                "fileAccessId": file_access_id,
                "fileName": file_name,
                "itemCount": item_count,
                "itemName": item_name,
                "materialAccessId": material_access_id,
                "materialColorAccessId": material_color_access_id,
                "materialDeliveryAccessId": material_delivery_access_id,
                "modelAccessId": model_access_id,
                "shippingAddress": shipping_address,
                "goodsCustomsType": goods_customs_type,
                "freightMode": freight_mode,
                "typeOfTrade": type_of_trade,
                "billingUseShippingAddressFlag": billing_use_shipping_address_flag,
                "billingAddress": billing_address,
                "batchNum": batch_num,
                "customerRemarks": customer_remarks,
                "goodsUsefulness": goods_usefulness,
                "itemPrice": item_price,
                "surfaceTreatmentProcess": surface_treatment_process,
                "craftShoppingCartDTOList": craft_shopping_cart_dto_list,
            },
        )

    def list_tdp_orders(
        self,
        *,
        current_page: int = 1,
        page_rows: int = 10,
        search_key: str | None = None,
        order_statistics_type: int | None = None,
        **extra: Any,
    ) -> dict:
        """List 3D-printing batch orders (paginated).

        ``order_statistics_type``: 1 last 30d, 2 last 6mo, 3 last 12mo, 4 over a
        year. Additional documented filters (``orderStatus``, ``businessType``, …)
        may be passed via ``**extra`` using their exact camelCase names.
        """
        return self._post(
            "/overseas/openapi/tdp/api/order/list",
            {
                "currentPage": current_page,
                "pageRows": page_rows,
                "searchKey": search_key,
                "orderStatisticsType": order_statistics_type,
                **extra,
            },
        )

    def get_tdp_order_detail(self, batch_num: str) -> dict:
        """Detail for one 3D-printing batch."""
        return self._post(
            "/overseas/openapi/tdp/api/order/detail",
            {"batchNum": batch_num},
        )

    def get_tdp_order_process(self, order_no: str) -> Any:
        """Manufacturing-stage timeline for one 3D-printing order number."""
        return self._post(
            "/overseas/openapi/tdp/api/order/process",
            {"orderNo": order_no},
        )


# -- module-level helpers ------------------------------------------------
def _success(envelope: dict) -> tuple[bool, Any, str]:
    """Return (is_success, code, message) for a JLC envelope.

    Handles the response-shape variants seen across services: the success flag is
    ``success`` (component/pcb) or ``successful`` (tdp upload), and the message is
    ``message`` (most) or ``msg`` (some tdp routes).
    """
    code = envelope.get("code", envelope.get("status"))
    flag = envelope.get("success")
    if flag is None:
        flag = envelope.get("successful")
    message = envelope.get("message") or envelope.get("msg") or ""
    ok = flag is True or code in (200, "200", 0, "0")
    return ok, code, message


def _unwrap(envelope: Any) -> Any:
    """Validate the response envelope and return its ``data`` payload."""
    if not isinstance(envelope, dict):
        return envelope
    ok, code, message = _success(envelope)
    if ok:
        return envelope.get("data")
    if envelope.get("success") is False or envelope.get("successful") is False or code is not None:
        raise JLCError(code, message, envelope.get("data"))
    return envelope.get("data")


def _check(envelope: Any) -> Any:
    """Raise :class:`JLCError` on a non-success envelope; otherwise return it unchanged.

    Used by uploads whose useful payload is not under ``data`` (e.g. TDP upload
    returns the file id in ``message``).
    """
    if isinstance(envelope, dict):
        ok, code, message = _success(envelope)
        if not ok:
            raise JLCError(code, message, envelope.get("data"))
    return envelope


def _read_file(file: Any, file_name: str | None) -> tuple[bytes, str]:
    """Coerce a path / bytes / binary file-like into ``(bytes, name)`` for upload."""
    if isinstance(file, (bytes, bytearray)):
        return bytes(file), file_name or "upload.bin"
    if hasattr(file, "read"):
        data = file.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        name = file_name or os.path.basename(str(getattr(file, "name", "") or "upload.bin"))
        return data, name
    path = os.fspath(file)
    with open(path, "rb") as fh:
        data = fh.read()
    return data, file_name or os.path.basename(path)
