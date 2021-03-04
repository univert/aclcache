import sys
import time
from ctypes import windll, wintypes, create_unicode_buffer, byref




def file1(n):
    for i in range(n):
        try:
            with open(r'U:\bin\RunRoot\Debug64\dbxsdk\dbxsdkrereg.wixout:aaaa','r') as f:
                a = f.read()
                pass
        except:pass

CreateFileW = windll.kernel32.CreateFileW
CloseHandle = windll.kernel32.CloseHandle
def file3(n):
    for i in range(n):
        a = CreateFileW(
            r'U:\bin\RunRoot\Debug64\dbxsdk\dbxsdkrereg.wixout:aaaa',
            1,  # FILE_APPEND_DATA | SYNCHRONIZE
            1,  # FILE_SHARE_READ | FILE_SHARE_WRITE
            None,
            3,  # OPEN_ALWAYS
            128,  # FILE_ATTRIBUTE_NORMAL
            None)

def main():
    start = time.time()
    file3(15000)
    end = time.time()
    print(end - start)

if __name__ == '__main__':
    sys.exit(main())



