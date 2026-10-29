"""Small native Keychain adapter for one-time Zotero setup, with no CLI secrets."""
from __future__ import annotations
import ctypes as c
import sys

SERVICE = "TransYH Zotero Setup"


def _frameworks():
    if sys.platform != "darwin":
        raise RuntimeError("Keychain bootstrap requires macOS")
    cf = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    sec = c.CDLL('/System/Library/Frameworks/Security.framework/Security')
    cf.CFStringCreateWithCString.argtypes=[c.c_void_p,c.c_char_p,c.c_uint32];cf.CFStringCreateWithCString.restype=c.c_void_p
    cf.CFDataCreate.argtypes=[c.c_void_p,c.c_void_p,c.c_long];cf.CFDataCreate.restype=c.c_void_p
    cf.CFDataGetLength.argtypes=[c.c_void_p];cf.CFDataGetLength.restype=c.c_long
    cf.CFDataGetBytePtr.argtypes=[c.c_void_p];cf.CFDataGetBytePtr.restype=c.c_void_p
    cf.CFDictionaryCreate.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_long,c.c_void_p,c.c_void_p];cf.CFDictionaryCreate.restype=c.c_void_p
    cf.CFRelease.argtypes=[c.c_void_p]
    sec.SecItemAdd.argtypes=[c.c_void_p,c.c_void_p];sec.SecItemAdd.restype=c.c_int32
    sec.SecItemUpdate.argtypes=[c.c_void_p,c.c_void_p];sec.SecItemUpdate.restype=c.c_int32
    sec.SecItemCopyMatching.argtypes=[c.c_void_p,c.POINTER(c.c_void_p)];sec.SecItemCopyMatching.restype=c.c_int32
    return cf,sec


class Query:
    def __init__(self, cf, sec, fields):
        self.cf=cf;self.owned=[]
        keys=[];values=[]
        for key,value in fields.items():
            keys.append(c.c_void_p.in_dll(sec,key).value)
            if isinstance(value,bytes):
                data=c.create_string_buffer(value)
                ptr=cf.CFDataCreate(None,data,len(value));self.owned.append(ptr)
            elif isinstance(value,str):
                ptr=cf.CFStringCreateWithCString(None,value.encode(),0x08000100);self.owned.append(ptr)
            else:ptr=value
            values.append(ptr)
        ka=(c.c_void_p*len(keys))(*keys);va=(c.c_void_p*len(values))(*values)
        self.ptr=cf.CFDictionaryCreate(None,ka,va,len(keys),None,None)
    def close(self):
        self.cf.CFRelease(self.ptr)
        for ptr in self.owned:self.cf.CFRelease(ptr)


def _identity(sec,base):
    return {'kSecClass':c.c_void_p.in_dll(sec,'kSecClassGenericPassword').value,
            'kSecAttrService':SERVICE,'kSecAttrAccount':base}


def put_api_key(base: str, key: str):
    cf,sec=_frameworks()
    query=Query(cf,sec,_identity(sec,base));changes=Query(cf,sec,{'kSecValueData':key.encode()})
    try:
        status=sec.SecItemUpdate(query.ptr,changes.ptr)
        if status == -25300:
            added=Query(cf,sec,{**_identity(sec,base),'kSecAttrLabel':'TransYH API setup','kSecValueData':key.encode()})
            try:status=sec.SecItemAdd(added.ptr,None)
            finally:added.close()
        if status:raise RuntimeError(f"Keychain write failed ({status})")
    finally:query.close();changes.close()


def get_api_key(base: str) -> str:
    cf,sec=_frameworks()
    query=Query(cf,sec,{**_identity(sec,base),'kSecReturnData':c.c_void_p.in_dll(cf,'kCFBooleanTrue').value,
        'kSecMatchLimit':c.c_void_p.in_dll(sec,'kSecMatchLimitOne').value})
    result=c.c_void_p()
    try:
        status=sec.SecItemCopyMatching(query.ptr,c.byref(result))
        if status:raise RuntimeError(f"Keychain read failed ({status})")
        return c.string_at(cf.CFDataGetBytePtr(result),cf.CFDataGetLength(result)).decode()
    finally:
        query.close()
        if result.value:cf.CFRelease(result)
