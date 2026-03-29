"""Lightweight protobuf encoding/decoding for ESPHome Native API messages.

Only implements the subset of protobuf needed for the Bluetooth Proxy protocol.
Wire format: https://protobuf.dev/programming-guides/encoding/
"""

from __future__ import annotations

import struct
from typing import Any

# Wire types
VARINT = 0
FIXED64 = 1
LENGTH_DELIMITED = 2
FIXED32 = 5


def encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    if value < 0:
        # Protobuf uses two's complement for signed varints
        value = value & 0xFFFFFFFFFFFFFFFF
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def encode_svarint(value: int) -> bytes:
    """Encode a signed integer using zigzag encoding."""
    zigzag = (value << 1) ^ (value >> 63)
    return encode_varint(zigzag)


def decode_varint(data: bytes | memoryview, offset: int) -> tuple[int, int]:
    """Decode a varint from data at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("Truncated varint")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return result, offset
        shift += 7
        if shift >= 64:
            raise ValueError("Varint too long")


def decode_svarint(data: bytes | memoryview, offset: int) -> tuple[int, int]:
    """Decode a zigzag-encoded signed varint."""
    value, offset = decode_varint(data, offset)
    # Undo zigzag
    return (value >> 1) ^ -(value & 1), offset


def encode_field_varint(field_number: int, value: int) -> bytes:
    """Encode a varint field."""
    if value == 0:
        return b""
    tag = encode_varint((field_number << 3) | VARINT)
    return tag + encode_varint(value)


def encode_field_svarint(field_number: int, value: int) -> bytes:
    """Encode a signed varint field (sint32/sint64)."""
    if value == 0:
        return b""
    tag = encode_varint((field_number << 3) | VARINT)
    return tag + encode_svarint(value)


def encode_field_bool(field_number: int, value: bool) -> bytes:
    """Encode a bool field."""
    if not value:
        return b""
    return encode_varint((field_number << 3) | VARINT) + b"\x01"


def encode_field_string(field_number: int, value: str) -> bytes:
    """Encode a string field."""
    if not value:
        return b""
    encoded = value.encode("utf-8")
    tag = encode_varint((field_number << 3) | LENGTH_DELIMITED)
    return tag + encode_varint(len(encoded)) + encoded


def encode_field_bytes(field_number: int, value: bytes) -> bytes:
    """Encode a bytes field."""
    if not value:
        return b""
    tag = encode_varint((field_number << 3) | LENGTH_DELIMITED)
    return tag + encode_varint(len(value)) + value


def encode_field_uint64(field_number: int, value: int) -> bytes:
    """Encode a uint64 field (as varint)."""
    return encode_field_varint(field_number, value)


def encode_field_int32(field_number: int, value: int) -> bytes:
    """Encode an int32 field (as varint, with sign extension)."""
    if value == 0:
        return b""
    tag = encode_varint((field_number << 3) | VARINT)
    if value < 0:
        return tag + encode_varint(value & 0xFFFFFFFFFFFFFFFF)
    return tag + encode_varint(value)


def encode_field_fixed32(field_number: int, value: int) -> bytes:
    """Encode a fixed32 field."""
    if value == 0:
        return b""
    tag = encode_varint((field_number << 3) | FIXED32)
    return tag + struct.pack("<I", value)


def encode_field_message(field_number: int, data: bytes) -> bytes:
    """Encode a sub-message field."""
    if not data:
        return b""
    tag = encode_varint((field_number << 3) | LENGTH_DELIMITED)
    return tag + encode_varint(len(data)) + data


def decode_fields(data: bytes | memoryview) -> dict[int, list[Any]]:
    """Decode all fields from a protobuf message.

    Returns a dict mapping field_number -> list of (wire_type, value).
    For varints, value is the integer.
    For length-delimited, value is bytes.
    For fixed32, value is 4 bytes.
    For fixed64, value is 8 bytes.
    """
    fields: dict[int, list[Any]] = {}
    offset = 0
    length = len(data)

    while offset < length:
        tag, offset = decode_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == VARINT:
            value, offset = decode_varint(data, offset)
        elif wire_type == LENGTH_DELIMITED:
            str_len, offset = decode_varint(data, offset)
            value = bytes(data[offset : offset + str_len])
            offset += str_len
        elif wire_type == FIXED32:
            value = bytes(data[offset : offset + 4])
            offset += 4
        elif wire_type == FIXED64:
            value = bytes(data[offset : offset + 8])
            offset += 8
        else:
            raise ValueError(f"Unknown wire type {wire_type}")

        fields.setdefault(field_number, []).append((wire_type, value))

    return fields


def get_field_varint(fields: dict, field_number: int, default: int = 0) -> int:
    """Get a varint field value."""
    entries = fields.get(field_number)
    if not entries:
        return default
    _, value = entries[0]
    return value


def get_field_bool(fields: dict, field_number: int, default: bool = False) -> bool:
    """Get a bool field value."""
    return bool(get_field_varint(fields, field_number, int(default)))


def get_field_string(fields: dict, field_number: int, default: str = "") -> str:
    """Get a string field value."""
    entries = fields.get(field_number)
    if not entries:
        return default
    _, value = entries[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return default


def get_field_bytes(fields: dict, field_number: int, default: bytes = b"") -> bytes:
    """Get a bytes field value."""
    entries = fields.get(field_number)
    if not entries:
        return default
    _, value = entries[0]
    if isinstance(value, bytes):
        return value
    return default


# =====================================================================
# ESPHome Native API message type IDs
# =====================================================================

# Base protocol
MSG_HELLO_REQUEST = 1
MSG_HELLO_RESPONSE = 2
MSG_CONNECT_REQUEST = 3
MSG_CONNECT_RESPONSE = 4
MSG_DISCONNECT_REQUEST = 5
MSG_DISCONNECT_RESPONSE = 6
MSG_PING_REQUEST = 7
MSG_PING_RESPONSE = 8
MSG_DEVICE_INFO_REQUEST = 9
MSG_DEVICE_INFO_RESPONSE = 10
MSG_LIST_ENTITIES_REQUEST = 11
MSG_LIST_ENTITIES_DONE_RESPONSE = 19
MSG_SUBSCRIBE_STATES_REQUEST = 20
MSG_SUBSCRIBE_LOGS_REQUEST = 28
MSG_SUBSCRIBE_HOMEASSISTANT_SERVICES_REQUEST = 34
MSG_GET_TIME_REQUEST = 36
MSG_SUBSCRIBE_HOMEASSISTANT_STATES_REQUEST = 38

# Bluetooth
MSG_SUBSCRIBE_BLE_ADVERTISEMENTS_REQUEST = 66
MSG_BLE_ADVERTISEMENT_RESPONSE = 67  # deprecated
MSG_BLE_DEVICE_REQUEST = 68
MSG_BLE_DEVICE_CONNECTION_RESPONSE = 69
MSG_BLE_GATT_GET_SERVICES_REQUEST = 70
MSG_BLE_GATT_GET_SERVICES_RESPONSE = 71
MSG_BLE_GATT_GET_SERVICES_DONE_RESPONSE = 72
MSG_BLE_GATT_READ_REQUEST = 73
MSG_BLE_GATT_READ_RESPONSE = 74
MSG_BLE_GATT_WRITE_REQUEST = 75
MSG_BLE_GATT_READ_DESCRIPTOR_REQUEST = 76
MSG_BLE_GATT_WRITE_DESCRIPTOR_REQUEST = 77
MSG_BLE_GATT_NOTIFY_REQUEST = 78
MSG_BLE_GATT_NOTIFY_DATA_RESPONSE = 79
MSG_SUBSCRIBE_BLE_CONNECTIONS_FREE_REQUEST = 80
MSG_BLE_CONNECTIONS_FREE_RESPONSE = 81
MSG_BLE_GATT_ERROR_RESPONSE = 82
MSG_BLE_GATT_WRITE_RESPONSE = 83
MSG_BLE_GATT_NOTIFY_RESPONSE = 84
MSG_BLE_DEVICE_PAIRING_RESPONSE = 85
MSG_BLE_DEVICE_UNPAIRING_RESPONSE = 86
MSG_UNSUBSCRIBE_BLE_ADVERTISEMENTS_REQUEST = 87
MSG_BLE_DEVICE_CLEAR_CACHE_RESPONSE = 88
MSG_BLE_RAW_ADVERTISEMENTS_RESPONSE = 93
MSG_BLE_SCANNER_STATE_RESPONSE = 126
MSG_BLE_SCANNER_SET_MODE_REQUEST = 127
MSG_BLE_SET_CONNECTION_PARAMS_REQUEST = 145
MSG_BLE_SET_CONNECTION_PARAMS_RESPONSE = 146

# Bluetooth device request types
BLE_REQUEST_CONNECT = 0  # V1 removed
BLE_REQUEST_DISCONNECT = 1
BLE_REQUEST_PAIR = 2
BLE_REQUEST_UNPAIR = 3
BLE_REQUEST_CONNECT_V3_WITH_CACHE = 4
BLE_REQUEST_CONNECT_V3_WITHOUT_CACHE = 5
BLE_REQUEST_CLEAR_CACHE = 6

# Bluetooth proxy feature flags
FEATURE_PASSIVE_SCAN = 1 << 0
FEATURE_ACTIVE_CONNECTIONS = 1 << 1
FEATURE_REMOTE_CACHING = 1 << 2
FEATURE_PAIRING = 1 << 3
FEATURE_CACHE_CLEARING = 1 << 4
FEATURE_RAW_ADVERTISEMENTS = 1 << 5
FEATURE_STATE_AND_MODE = 1 << 6

# Scanner states
SCANNER_STATE_IDLE = 0
SCANNER_STATE_STARTING = 1
SCANNER_STATE_RUNNING = 2
SCANNER_STATE_FAILED = 3
SCANNER_STATE_STOPPING = 4
SCANNER_STATE_STOPPED = 5

# Scanner modes
SCANNER_MODE_PASSIVE = 0
SCANNER_MODE_ACTIVE = 1


# =====================================================================
# Wire protocol framing
# =====================================================================


def frame_message(msg_type: int, data: bytes) -> bytes:
    """Frame a protobuf message for the ESPHome Native API wire protocol.

    Format: 0x00 + varint(data_length) + varint(msg_type) + data
    where data_length = len(data) (does NOT include msg_type varint).
    """
    return b"\x00" + encode_varint(len(data)) + encode_varint(msg_type) + data


# =====================================================================
# Message encoders (server -> client)
# =====================================================================


def encode_hello_response(
    api_version_major: int = 1,
    api_version_minor: int = 10,
    server_info: str = "",
    name: str = "",
) -> bytes:
    """Encode HelloResponse."""
    return (
        encode_field_varint(1, api_version_major)
        + encode_field_varint(2, api_version_minor)
        + encode_field_string(3, server_info)
        + encode_field_string(4, name)
    )


def encode_device_info_response(
    name: str = "",
    mac_address: str = "",
    esphome_version: str = "",
    model: str = "",
    manufacturer: str = "",
    friendly_name: str = "",
    bluetooth_proxy_feature_flags: int = 0,
    bluetooth_mac_address: str = "",
) -> bytes:
    """Encode DeviceInfoResponse."""
    return (
        encode_field_string(2, name)
        + encode_field_string(3, mac_address)
        + encode_field_string(4, esphome_version)
        + encode_field_string(6, model)
        + encode_field_varint(15, bluetooth_proxy_feature_flags)
        + encode_field_string(12, manufacturer)
        + encode_field_string(13, friendly_name)
        + encode_field_string(18, bluetooth_mac_address)
    )


def encode_ble_raw_advertisement(
    address: int, rssi: int, address_type: int, data: bytes
) -> bytes:
    """Encode a single BluetoothLERawAdvertisement sub-message."""
    return (
        encode_field_uint64(1, address)
        + encode_field_svarint(2, rssi)
        + encode_field_varint(3, address_type)
        + encode_field_bytes(4, data)
    )


def encode_ble_raw_advertisements_response(
    advertisements: list[tuple[int, int, int, bytes]],
) -> bytes:
    """Encode BluetoothLERawAdvertisementsResponse.

    Each advertisement is (address, rssi, address_type, raw_data).
    """
    result = b""
    for address, rssi, address_type, data in advertisements:
        adv_msg = encode_ble_raw_advertisement(address, rssi, address_type, data)
        result += encode_field_message(1, adv_msg)
    return result


def encode_ble_device_connection_response(
    address: int, connected: bool, mtu: int = 0, error: int = 0
) -> bytes:
    """Encode BluetoothDeviceConnectionResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_bool(2, connected)
        + encode_field_varint(3, mtu)
        + encode_field_int32(4, error)
    )


def encode_ble_connections_free_response(
    free: int, limit: int, allocated: list[int] | None = None
) -> bytes:
    """Encode BluetoothConnectionsFreeResponse."""
    result = encode_field_varint(1, free) + encode_field_varint(2, limit)
    if allocated:
        for addr in allocated:
            result += encode_field_uint64(3, addr)
    return result


def encode_ble_gatt_service(
    uuid: list[int], handle: int, characteristics: list[bytes]
) -> bytes:
    """Encode a BluetoothGATTService sub-message."""
    result = b""
    for u in uuid:
        result += encode_field_uint64(1, u)
    result += encode_field_varint(2, handle)
    for char_data in characteristics:
        result += encode_field_message(3, char_data)
    return result


def encode_ble_gatt_characteristic(
    uuid: list[int], handle: int, properties: int, descriptors: list[bytes]
) -> bytes:
    """Encode a BluetoothGATTCharacteristic sub-message."""
    result = b""
    for u in uuid:
        result += encode_field_uint64(1, u)
    result += encode_field_varint(2, handle)
    result += encode_field_varint(3, properties)
    for desc_data in descriptors:
        result += encode_field_message(4, desc_data)
    return result


def encode_ble_gatt_descriptor(uuid: list[int], handle: int) -> bytes:
    """Encode a BluetoothGATTDescriptor sub-message."""
    result = b""
    for u in uuid:
        result += encode_field_uint64(1, u)
    result += encode_field_varint(2, handle)
    return result


def encode_ble_gatt_services_response(
    address: int, services: list[bytes]
) -> bytes:
    """Encode BluetoothGATTGetServicesResponse."""
    result = encode_field_uint64(1, address)
    for svc in services:
        result += encode_field_message(2, svc)
    return result


def encode_ble_gatt_services_done_response(address: int) -> bytes:
    """Encode BluetoothGATTGetServicesDoneResponse."""
    return encode_field_uint64(1, address)


def encode_ble_gatt_read_response(
    address: int, handle: int, data: bytes
) -> bytes:
    """Encode BluetoothGATTReadResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_varint(2, handle)
        + encode_field_bytes(3, data)
    )


def encode_ble_gatt_write_response(address: int, handle: int) -> bytes:
    """Encode BluetoothGATTWriteResponse."""
    return encode_field_uint64(1, address) + encode_field_varint(2, handle)


def encode_ble_gatt_notify_response(address: int, handle: int) -> bytes:
    """Encode BluetoothGATTNotifyResponse."""
    return encode_field_uint64(1, address) + encode_field_varint(2, handle)


def encode_ble_gatt_notify_data_response(
    address: int, handle: int, data: bytes
) -> bytes:
    """Encode BluetoothGATTNotifyDataResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_varint(2, handle)
        + encode_field_bytes(3, data)
    )


def encode_ble_gatt_error_response(
    address: int, handle: int, error: int
) -> bytes:
    """Encode BluetoothGATTErrorResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_varint(2, handle)
        + encode_field_int32(3, error)
    )


def encode_ble_scanner_state_response(
    state: int, mode: int, configured_mode: int
) -> bytes:
    """Encode BluetoothScannerStateResponse."""
    return (
        encode_field_varint(1, state)
        + encode_field_varint(2, mode)
        + encode_field_varint(3, configured_mode)
    )


def encode_ble_device_pairing_response(
    address: int, paired: bool, error: int = 0
) -> bytes:
    """Encode BluetoothDevicePairingResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_bool(2, paired)
        + encode_field_int32(3, error)
    )


def encode_ble_device_unpairing_response(
    address: int, success: bool, error: int = 0
) -> bytes:
    """Encode BluetoothDeviceUnpairingResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_bool(2, success)
        + encode_field_int32(3, error)
    )


def encode_ble_device_clear_cache_response(
    address: int, success: bool, error: int = 0
) -> bytes:
    """Encode BluetoothDeviceClearCacheResponse."""
    return (
        encode_field_uint64(1, address)
        + encode_field_bool(2, success)
        + encode_field_int32(3, error)
    )


# =====================================================================
# BLE address utilities
# =====================================================================


def mac_to_int(mac: str) -> int:
    """Convert a MAC address string 'AA:BB:CC:DD:EE:FF' to a uint64."""
    parts = mac.split(":")
    result = 0
    for part in parts:
        result = (result << 8) | int(part, 16)
    return result


def int_to_mac(value: int) -> str:
    """Convert a uint64 to a MAC address string 'AA:BB:CC:DD:EE:FF'."""
    parts = []
    for _ in range(6):
        parts.append(f"{value & 0xFF:02X}")
        value >>= 8
    return ":".join(reversed(parts))


def uuid_to_128bit_ints(uuid_str: str) -> list[int]:
    """Convert a UUID string to the two uint64 values used by ESPHome.

    ESPHome packs 128-bit UUIDs into two uint64 values:
    - uuid[0] = bytes 8-15 (big-endian)
    - uuid[1] = bytes 0-7 (big-endian)
    """
    # Remove dashes and parse as hex
    hex_str = uuid_str.replace("-", "")
    uuid_bytes = bytes.fromhex(hex_str)

    # uuid[0] = bytes 8-15 (big-endian) = high part
    high = int.from_bytes(uuid_bytes[0:8], "big")
    # uuid[1] = bytes 0-7 (big-endian) = low part
    low = int.from_bytes(uuid_bytes[8:16], "big")

    return [high, low]
