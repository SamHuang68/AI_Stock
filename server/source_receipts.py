"""來源回應保留兩項解包契約；只有實際 fetch 能附加原始收據。"""


class JsonSourceResponse(tuple):
    def __new__(cls, value, digest, source_receipt=None):
        response = super().__new__(cls, (value, digest))
        response.source_receipt = source_receipt
        return response
