"""Constants for the Evri integration."""

DOMAIN = "evri"
CONF_API_KEY = "apiKey"
API_KEY = "RGVplG9He66OnnAjnGKz7Ovol9dKbSAr"
CONF_GET = "GET"
UNIQUE_ID_URL = "https://api.hermesworld.co.uk/enterprise-tracking-api/v1/parcels/search/{trackingNumber}"
TRACKING_INFO_URL = "https://api.hermesworld.co.uk/enterprise-tracking-api/v1/parcels/?uniqueIds={uniqueIds}&postcode={postCode}"
CONF_TRACK_A_PARCEL = "track_a_parcel"
CONF_TRACKING_NUMBER = "tracking_number"
CONF_POST_CODE = "postcode"
REQUEST_HEADERS = {"apiKey": "RGVplG9He66OnnAjnGKz7Ovol9dKbSAr"}
PARCEL_DELIVERED = ["5_COURIER"]
PARCEL_DELIVERY_TODAY = ["4_COURIER"]
PARCEL_IN_TRANSIT = ["1", "2", "3"]
CONF_TRACKINGEVENTS = "trackingEvents"
CONF_TRACKINGSTAGE = "trackingStage"
CONF_TRACKINGSTAGECODE = "trackingStageCode"
CONF_DESCRIPTION = "description"
CONF_SENDER = "sender"
CONF_DISPLAYNAME = "displayName"
CONF_PARCELIDENTIFIERS = "parcelIdentifiers"
CONF_VALUE = "value"
CONF_PARCELS = "parcels"
CONF_RESULTS = "results"
CONF_DATETIME = "dateTime"
CONF_OUT_FOR_DELIVERY = "outForDelivery"
