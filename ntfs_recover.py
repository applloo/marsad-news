#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
استرجاع الملفات المحذوفة من فهرس NTFS (MFT) بسرعة.

بيقرأ الفهرس بس (مش بيفتح كل الهارد)، فبيخلص في دقايق.
بيقرا من الهارد ومبيكتبش عليه أبدًا. الملفات بتتنسخ على مكان تاني إنت بتحدده.

أوضاع التشغيل:
    python ntfs_recover.py            -> نافذة بقوايم اختيار (محتاج Administrator)
    python ntfs_recover.py --text     -> قوايم بالكتابة في الشاشة السودا
    python ntfs_recover.py --source D: --folder Photos --types "*.jpg;*.mp4" --dest E:\\out
"""
import argparse
import fnmatch
import os
import re
import struct
import sys
import time

# ----------------------------------------------------------------- أدوات صغيرة


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


ALIGN = 4096  # القراءة من الهارد لازم تبقى بمضاعفات حجم القطاع


class RawReader:
    """قراءة فقط. بتظبط القراءة على حدود القطاعات عشان تشتغل مع \\\\.\\D:"""

    def __init__(self, path):
        self.f = open(path, "rb", buffering=0)

    def read(self, offset, length):
        if length <= 0:
            return b""
        start = offset - offset % ALIGN
        end = ((offset + length + ALIGN - 1) // ALIGN) * ALIGN
        self.f.seek(start)
        data = self.f.read(end - start)
        return data[offset - start: offset - start + length]

    def close(self):
        self.f.close()


def source_to_path(src):
    """D: أو D أو D:\\  ->  \\\\.\\D:   وأي حاجة تانية بتتعامل كملف صورة"""
    m = re.fullmatch(r"([A-Za-z]):?[\\/]?", src.strip())
    if m and os.name == "nt":
        return "\\\\.\\" + m.group(1).upper() + ":"
    return src


def apply_fixup(rec):
    """NTFS بيبدّل آخر 2 بايت من كل 512 بايت. هنرجعهم لأصلهم."""
    if rec[0:4] != b"FILE":
        return False
    uo, uc = u16(rec, 4), u16(rec, 6)
    if uc < 2 or uo + 2 * uc > len(rec):
        return False
    usn = bytes(rec[uo:uo + 2])
    for i in range(1, uc):
        end = i * 512
        if end > len(rec):
            return False
        if bytes(rec[end - 2:end]) != usn:
            return False
        rec[end - 2:end] = rec[uo + 2 * i: uo + 2 * i + 2]
    return True


def parse_runs(buf, off):
    """بيفك خريطة أماكن الملف على الهارد: [(أول كلستر, عدد كلسترات)]"""
    runs, lcn = [], 0
    n = len(buf)
    while off < n:
        h = buf[off]
        if h == 0:
            break
        ln, lo = h & 0x0F, h >> 4
        off += 1
        if ln == 0 or off + ln + lo > n:
            break
        length = int.from_bytes(buf[off:off + ln], "little")
        off += ln
        if lo == 0:
            runs.append((None, length))  # مساحة فاضية (sparse)
        else:
            lcn += int.from_bytes(buf[off:off + lo], "little", signed=True)
            off += lo
            runs.append((lcn, length))
    return runs


class Parsed:
    __slots__ = ("recno", "seq", "in_use", "is_dir", "base", "name", "parent",
                 "pseq", "data", "attr_list")


def parse_record(rec, recno):
    flags = u16(rec, 0x16)
    p = Parsed()
    p.recno = recno
    p.seq = u16(rec, 0x10)
    p.in_use = bool(flags & 1)
    p.is_dir = bool(flags & 2)
    p.base = u64(rec, 0x20) & 0xFFFFFFFFFFFF
    p.name = None
    p.parent = 0
    p.pseq = 0
    p.data = None   # dict: nonres, svcn, real, runs, content, aflags
    p.attr_list = False
    names = []
    off = u16(rec, 0x14)
    ln = len(rec)
    while off + 16 <= ln:
        t = u32(rec, off)
        if t == 0xFFFFFFFF:
            break
        alen = u32(rec, off + 4)
        if alen < 16 or off + alen > ln:
            break
        nonres = rec[off + 8]
        nlen = rec[off + 9]
        aflags = u16(rec, off + 12)
        if t == 0x30 and not nonres:
            co, cs = u16(rec, off + 0x14), u32(rec, off + 0x10)
            c = rec[off + co: off + co + cs]
            if len(c) >= 0x42:
                par = u64(c, 0)
                nl, ns = c[0x40], c[0x41]
                nm = bytes(c[0x42:0x42 + nl * 2]).decode("utf-16le", "replace")
                names.append((ns, nm, par & 0xFFFFFFFFFFFF, par >> 48))
        elif t == 0x80 and nlen == 0:
            if nonres:
                ro = u16(rec, off + 0x20)
                p.data = dict(nonres=True, svcn=u64(rec, off + 0x10),
                              real=u64(rec, off + 0x30),
                              runs=parse_runs(bytes(rec[off:off + alen]), ro),
                              aflags=aflags)
            else:
                co, cs = u16(rec, off + 0x14), u32(rec, off + 0x10)
                p.data = dict(nonres=False, svcn=0, real=cs,
                              content=bytes(rec[off + co: off + co + cs]),
                              aflags=aflags)
        elif t == 0x20:
            p.attr_list = True
        off += alen
    if names:
        good = [x for x in names if x[0] != 2]  # نفضّل الاسم الطويل مش DOS
        ns, nm, par, ps = (good or names)[0]
        p.name, p.parent, p.pseq = nm, par, ps
    return p


class FileEntry:
    __slots__ = ("recno", "name", "parent", "pseq", "in_use", "frags", "attr_list",
                 "path", "size", "status")


class DirEntry:
    __slots__ = ("name", "parent", "pseq", "in_use", "seq")


# ----------------------------------------------------------------- الفولوم


class Volume:
    def __init__(self, source):
        self.source = source
        self.reader = RawReader(source_to_path(source))
        b = self.reader.read(0, 512)
        if b[3:11] != b"NTFS    ":
            raise ValueError("البارتيشن ده مش NTFS (يمكن FAT أو exFAT).")
        bps, spc = u16(b, 0x0B), b[0x0D]
        self.cs = bps * spc                       # حجم الكلستر بالبايت
        self.total_clusters = u64(b, 0x28) * bps // self.cs
        self.mft_lcn = u64(b, 0x30)
        cpr = struct.unpack("b", b[0x40:0x41])[0]
        self.rec_size = cpr * self.cs if cpr > 0 else 1 << (-cpr)
        self.dirs = {}
        self.files = {}
        self.ext = {}
        self.bitmap = None
        self.scanned = False

    # قراءة سجل واحد من الفهرس (للسجل 0 و 6)
    def _mft_record(self, recno, mft_runs=None):
        if mft_runs is None:
            off = self.mft_lcn * self.cs + recno * self.rec_size
        else:
            pos = recno * self.rec_size
            off = None
            for lcn, length in mft_runs:
                sz = length * self.cs
                if pos < sz:
                    off = lcn * self.cs + pos
                    break
                pos -= sz
            if off is None:
                raise ValueError("سجل خارج الفهرس")
        rec = bytearray(self.reader.read(off, self.rec_size))
        if not apply_fixup(rec):
            raise ValueError("سجل الفهرس رقم %d تالف" % recno)
        return rec

    def _read_data(self, runs, size):
        out = bytearray()
        for lcn, length in runs:
            n = length * self.cs
            if lcn is None:
                out += bytes(n)
            else:
                out += self.reader.read(lcn * self.cs, n)
            if len(out) >= size:
                break
        return bytes(out[:size])

    def scan(self, progress=None, include_existing=False):
        rec0 = self._mft_record(0)
        p0 = parse_record(rec0, 0)
        if not p0.data or not p0.data["nonres"]:
            raise ValueError("مش قادر أقرا خريطة الفهرس $MFT")
        mft_runs = p0.data["runs"]
        mft_size = p0.data["real"]
        nrec = mft_size // self.rec_size
        # الـ Bitmap بتقول أنهي كلسترات مستخدمة دلوقتي
        try:
            r6 = parse_record(self._mft_record(6, mft_runs), 6)
            self.bitmap = self._read_data(r6.data["runs"], (self.total_clusters + 7) // 8)
        except Exception:
            self.bitmap = None

        self.dirs, self.files, self.ext = {}, {}, {}
        chunk = max(1, (4 << 20) // self.rec_size) * self.rec_size
        recno = 0
        last = time.time()
        for lcn, length in mft_runs:
            total = length * self.cs
            if lcn is None:
                recno += total // self.rec_size
                continue
            pos, end = lcn * self.cs, lcn * self.cs + total
            while pos < end and recno < nrec:
                buf = self.reader.read(pos, min(chunk, end - pos))
                for i in range(0, len(buf) - self.rec_size + 1, self.rec_size):
                    if recno >= nrec:
                        break
                    if buf[i:i + 4] == b"FILE":
                        rec = bytearray(buf[i:i + self.rec_size])
                        if apply_fixup(rec):
                            self._take(parse_record(rec, recno), include_existing)
                    recno += 1
                pos += len(buf)
                if progress and time.time() - last > 0.3:
                    progress(recno, nrec)
                    last = time.time()
        if progress:
            progress(nrec, nrec)
        self.scanned = True
        self.dir_cache = {}
        return nrec

    def _take(self, p, include_existing):
        if p.base:   # سجل إضافي (ملحق) لملف تاني: بنحتفظ بأجزاء الداتا بس
            if p.data and p.data["nonres"] and (not p.in_use or include_existing):
                self.ext.setdefault(p.base, []).append(p.data)
            return
        if p.name is None:
            return
        if p.is_dir:
            d = DirEntry()
            d.name, d.parent, d.pseq, d.in_use, d.seq = p.name, p.parent, p.pseq, p.in_use, p.seq
            self.dirs[p.recno] = d
        elif (not p.in_use) or include_existing:
            f = FileEntry()
            f.recno, f.name, f.parent, f.pseq = p.recno, p.name, p.parent, p.pseq
            f.in_use, f.attr_list = p.in_use, p.attr_list
            f.frags = [p.data] if p.data else []
            f.path = f.size = f.status = None
            self.files[p.recno] = f

    # ------------------------------------------------------------- المسارات
    def dir_path(self, rec, exp_seq):
        if rec == 5:
            return ""
        stack, cur, exp, seen = [], rec, exp_seq, set()
        base = None
        while True:
            if cur == 5:
                base = ""
                break
            if cur in self.dir_cache:
                base = self.dir_cache[cur]
                break
            d = self.dirs.get(cur)
            ok = d is not None and cur not in seen and (
                d.seq == exp if d.in_use else d.seq in (exp, exp + 1))
            if not ok:
                base = "_مفقود_%d" % cur
                break
            seen.add(cur)
            stack.append(cur)
            cur, exp = d.parent, d.pseq
        for r in reversed(stack):
            nm = self.dirs[r].name
            base = (base + "\\" + nm) if base else nm
            self.dir_cache[r] = base
        return base

    # ------------------------------------------------------------- حالة الكلسترات
    def _count_used(self, start, length):
        bm = self.bitmap
        if bm is None:
            return 0
        used, c, end = 0, start, start + length
        while c < end and c % 8:
            used += (bm[c >> 3] >> (c & 7)) & 1
            c += 1
        full = (end - c) // 8
        if full > 0:
            used += int.from_bytes(bm[c >> 3:(c >> 3) + full], "little").bit_count()
            c += full * 8
        while c < end:
            used += (bm[c >> 3] >> (c & 7)) & 1
            c += 1
        return used

    def _runs_and_size(self, f):
        frags = list(f.frags) + list(self.ext.get(f.recno, []))
        if not frags:
            return None, 0, None
        frags.sort(key=lambda d: d["svcn"])
        first = frags[0]
        if not first["nonres"]:
            return [], first["real"], first
        runs = []
        for d in frags:
            runs += d["runs"]
        return runs, first["real"], first

    def finish(self, f):
        if f.path is not None:
            return
        f.path = self.dir_path(f.parent, f.pseq)
        runs, size, first = self._runs_and_size(f)
        f.size = size
        if first is None:
            f.status = "فاضي"
        elif first["aflags"] & 0x8000:
            f.status = "مشفر من ويندوز (متخطي)"
        elif first["aflags"] & 0x0001:
            f.status = "مضغوط (متخطي)"
        elif not first["nonres"]:
            f.status = "كامل (صغير)"
        elif self.bitmap is None:
            f.status = "مش عارف"
        else:
            tot = used = 0
            for lcn, ln in runs:
                if lcn is None:
                    continue
                tot += ln
                used += self._count_used(lcn, ln)
            if tot == 0:
                f.status = "فاضي"
            elif used == 0:
                f.status = "كامل"
            elif used == tot:
                f.status = "مكتوب عليه"
            else:
                f.status = "جزء مكتوب عليه"
        if f.attr_list and f.status in ("كامل", "كامل (صغير)"):
            f.status += " (ملف مقسّم)"

    # ------------------------------------------------------------- البحث
    def search(self, folder="", types="", skip_overwritten=False):
        folder = folder.strip().strip("\\/").lower().replace("/", "\\")
        pats = [x.strip().lower() for x in re.split(r"[;,|]", types or "") if x.strip()]
        pats = [x if any(ch in x for ch in "*?") else "*" + x + "*" for x in pats]
        res = []
        for f in self.files.values():
            nm = f.name.lower()
            if pats and not any(fnmatch.fnmatchcase(nm, p) for p in pats):
                continue
            self.finish(f)
            if folder and folder not in f.path.lower():
                continue
            if skip_overwritten and f.status.startswith("مكتوب"):
                continue
            res.append(f)
        res.sort(key=lambda x: (x.path.lower(), x.name.lower()))
        return res

    def folder_summary(self, types="", top=1000):
        """لكل فولدر: (المسار، عدد الملفات، الحجم الكلي، عدد الملفات اللي فوق 100KB). مرتبين بالحجم الكلي."""
        agg = {}
        for f in self.search(folder="", types=types):
            a = agg.setdefault(f.path, [0, 0, 0])
            a[0] += 1
            a[1] += f.size or 0
            if (f.size or 0) >= 100 * 1024:
                a[2] += 1
        items = sorted(agg.items(), key=lambda kv: -kv[1][1])[:top]
        return [(p, v[0], v[1], v[2]) for p, v in items]

    # ------------------------------------------------------------- الاسترجاع
    def recover(self, f, dest_root, progress=None):
        self.finish(f)
        if f.status.startswith(("مشفر", "مضغوط")):
            return None, f.status
        runs, size, first = self._runs_and_size(f)
        rel = os.path.join(*[safe_name(x) for x in (f.path.split("\\") if f.path else [])],
                           safe_name(f.name)) if f.path else safe_name(f.name)
        out = os.path.join(dest_root, rel)
        os.makedirs(lp(os.path.dirname(out) or "."), exist_ok=True)
        base, ext = os.path.splitext(out)
        k = 1
        while os.path.exists(lp(out)):
            k += 1
            out = "%s (%d)%s" % (base, k, ext)
        if first is None:
            open(lp(out), "wb").close()
            return out, "فاضي"
        with open(lp(out), "wb") as w:
            if not first["nonres"]:
                w.write(first["content"])
            else:
                left = size
                for lcn, length in runs:
                    n = min(length * self.cs, left)
                    done = 0
                    while done < n:
                        part = min(8 << 20, n - done)
                        if lcn is None:
                            w.write(bytes(part))
                        else:
                            w.write(self.reader.read(lcn * self.cs + done, part))
                        done += part
                    left -= n
                    if left <= 0:
                        break
        return out, f.status

    def close(self):
        self.reader.close()


def lp(p):
    """مسارات الفولدرات العميقة: ويندوز بيرفض المسار لو عدّى 260 حرف، فبنضيف بادئة المسارات الطويلة."""
    if os.name != "nt":
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).rstrip(" .")
    return s or "_"


def fmt_size(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0


TYPE_PRESETS = [
    ("كل الأنواع", ""),
    ("صور", "*.jpg;*.jpeg;*.png;*.heic;*.gif;*.bmp;*.webp;*.raw;*.cr2;*.nef;*.dng"),
    ("فيديو", "*.mp4;*.mov;*.avi;*.mkv;*.3gp;*.wmv;*.mts;*.m4v;*.flv"),
    ("صور وفيديو", "*.jpg;*.jpeg;*.png;*.heic;*.gif;*.mp4;*.mov;*.avi;*.mkv;*.3gp;*.wmv;*.mts;*.m4v"),
    ("مستندات", "*.doc;*.docx;*.xls;*.xlsx;*.ppt;*.pptx;*.pdf;*.txt"),
]


def same_drive(a, b):
    da, db = os.path.splitdrive(os.path.abspath(a))[0].upper(), os.path.splitdrive(os.path.abspath(b))[0].upper()
    return bool(da) and da == db


def run_recovery(vol, results, dest, log=print, tick=None):
    ok = fail = 0
    for i, f in enumerate(results):
        try:
            out, st = vol.recover(f, dest)
            if out:
                ok += 1
            else:
                fail += 1
                log("اتخطّى: %s\\%s (%s)" % (f.path, f.name, st))
        except Exception as e:  # noqa
            fail += 1
            log("فشل: %s\\%s (%s)" % (f.path, f.name, e))
        if tick:
            tick(i + 1, len(results))
    return ok, fail


# ----------------------------------------------------------------- الوضع النصي


def list_drives():
    if os.name != "nt":
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask >> i & 1:
            letter = chr(65 + i) + ":"
            t = ctypes.windll.kernel32.GetDriveTypeW(letter + "\\")
            if t in (2, 3):
                out.append(letter)
    return out


def ask(prompt, default=""):
    s = input(prompt).strip()
    return s or default


def text_mode(args):
    print("=== استرجاع الملفات المحذوفة من فهرس NTFS ===")
    src = args.source
    if not src:
        drives = list_drives()
        for i, d in enumerate(drives, 1):
            print("  %d) %s" % (i, d))
        s = ask("اختار رقم البارتيشن (أو اكتب مسار ملف صورة): ")
        src = drives[int(s) - 1] if s.isdigit() and 0 < int(s) <= len(drives) else s
    vol = Volume(src)
    print("بقرا الفهرس... (دقايق)")
    vol.scan(lambda a, b: print("\r  %d%%" % (100 * a // max(b, 1)), end="", flush=True))
    print("\nخلصت. لقيت %d ملف محذوف." % len(vol.files))
    while True:
        for i, (n, _) in enumerate(TYPE_PRESETS, 1):
            print("  %d) %s" % (i, n))
        s = ask("اختار نوع الملفات [1]: ", "1")
        types = TYPE_PRESETS[int(s) - 1][1] if s.isdigit() and 0 < int(s) <= len(TYPE_PRESETS) else s
        items = vol.folder_summary(types, top=25)
        print("الفولدرات اللي فيها ملفات محذوفة:")
        print("  0) كل الفولدرات")
        for i, (p, c, sz, big) in enumerate(items, 1):
            print("  %d) %s   (%d ملف - %s - %d فوق 100KB)" % (i, p or "<جذر البارتيشن>", c, fmt_size(sz), big))
        s = ask("اختار رقم فولدر، أو اكتب جزء من اسمه [0]: ", "0")
        folder = "" if s == "0" else (items[int(s) - 1][0] if s.isdigit() and int(s) <= len(items) else s)
        name = ask("اسم ملف معين أو جزء منه (فاضي = الكل): ")
        res = vol.search(folder, ";".join(x for x in [types] if x) if not name else name)
        if name and types:   # اسم + نوع
            res = [f for f in res if any(fnmatch.fnmatchcase(f.name.lower(), p.strip().lower())
                                         for p in types.split(";") if p.strip())]
        tot = sum(f.size or 0 for f in res)
        print("النتيجة: %d ملف، الحجم %s" % (len(res), fmt_size(tot)))
        for f in res[:30]:
            print("  [%s] %s\\%s  %s" % (f.status, f.path, f.name, fmt_size(f.size or 0)))
        if len(res) > 30:
            print("  ... و %d كمان" % (len(res) - 30))
        d = ask("اكتب فولدر الحفظ (على هارد تاني!) أو Enter للبحث من جديد: ")
        if d:
            if same_drive(d, src):
                print("لأ! الحفظ لازم يبقى على هارد غير اللي بتسترجع منه.")
                continue
            ok, fail = run_recovery(vol, res, d)
            print("تم: %d اتسترجع، %d متخطّى/فشل. راجع فولدر %s" % (ok, fail, d))
        if ask("بحث تاني؟ (ن/لا) [لا]: ", "لا") not in ("ن", "y", "Y", "نعم"):
            break
    vol.close()


# ----------------------------------------------------------------- الشاشة


def gui_mode():
    import threading
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("استرجاع الملفات المحذوفة")
    root.geometry("1100x690")
    F = ("Segoe UI", 15)
    FB = ("Segoe UI", 15, "bold")
    st = {"vol": None, "res": []}

    def row(parent):
        fr = tk.Frame(parent)
        fr.pack(fill="x", padx=12, pady=6)
        return fr

    r1 = row(root)
    tk.Label(r1, text="البارتيشن:", font=FB).pack(side="right")
    drive = ttk.Combobox(r1, values=list_drives(), font=F, width=8)
    drive.pack(side="right", padx=8)
    if drive["values"]:
        drive.current(0)
    btn_scan = tk.Button(r1, text="1) اقرا الفهرس", font=FB, bg="#2e7d32", fg="white")
    btn_scan.pack(side="right", padx=8)
    status = tk.Label(root, text="جاهز", font=F, anchor="e")
    status.pack(fill="x", padx=12)
    bar = ttk.Progressbar(root, maximum=100)
    bar.pack(fill="x", padx=12, pady=4)

    r2 = row(root)
    tk.Label(r2, text="نوع الملفات:", font=FB).pack(side="right")
    tcombo = ttk.Combobox(r2, values=[n for n, _ in TYPE_PRESETS], font=F, width=16)
    tcombo.current(0)
    tcombo.pack(side="right", padx=8)
    tk.Label(r2, text="اسم ملف (اختياري):", font=FB).pack(side="right", padx=(20, 0))
    name_e = tk.Entry(r2, font=F, width=18)
    name_e.pack(side="right", padx=8)

    r3 = row(root)
    tk.Label(r3, text="الفولدر:", font=FB).pack(side="right")
    fcombo = ttk.Combobox(r3, font=F, width=60)
    fcombo.pack(side="right", padx=8)
    btn_folders = tk.Button(r3, text="حدّث قايمة الفولدرات", font=F)
    btn_folders.pack(side="right", padx=8)

    r4 = row(root)
    btn_search = tk.Button(r4, text="2) ابحث", font=FB, bg="#1565c0", fg="white")
    btn_search.pack(side="right", padx=8)
    skip_var = tk.BooleanVar(value=False)
    tk.Checkbutton(r4, text="اخفي اللي مكتوب عليه", variable=skip_var, font=F).pack(side="right", padx=10)

    cols = ("status", "size", "path", "name")
    tree = ttk.Treeview(root, columns=cols, show="headings", height=12)
    for c, t, w in (("status", "الحالة", 140), ("size", "الحجم", 100), ("path", "الفولدر", 450), ("name", "الاسم", 300)):
        tree.heading(c, text=t + " ⇅", command=lambda c=c: sort_by(c))
        tree.column(c, width=w, anchor="e")
    style = ttk.Style()
    style.configure("Treeview", font=("Segoe UI", 12), rowheight=28)

    r5 = row(root)
    tk.Label(r5, text="احفظ في (هارد تاني):", font=FB).pack(side="right")
    dest_e = tk.Entry(r5, font=F, width=40)
    dest_e.pack(side="right", padx=8)
    tk.Button(r5, text="اختار...", font=F,
              command=lambda: (lambda d: (dest_e.delete(0, "end"), dest_e.insert(0, d)) if d else None)(
                  filedialog.askdirectory())).pack(side="right")
    btn_rec = tk.Button(root, text="3) استرجع كل النتايج دي", font=("Segoe UI", 17, "bold"),
                        bg="#c62828", fg="white")
    # الزرار وخانة الحفظ يتثبتوا تحت الأول، والجدول ياخد الباقي (عشان ميتقصّوش في الشاشات الصغيرة)
    r5.pack_forget()
    btn_rec.pack(side="bottom", fill="x", padx=12, pady=8)
    r5.pack(side="bottom", fill="x", padx=12, pady=6)
    tree.pack(fill="both", expand=True, padx=12, pady=6)

    def set_status(t):
        root.after(0, lambda: status.config(text=t))

    def set_prog(a, b):
        root.after(0, lambda: bar.config(value=100.0 * a / max(b, 1)))

    def types_value():
        t = tcombo.get().strip()
        for n, v in TYPE_PRESETS:
            if n == t:
                return v
        return t

    def work(fn):
        def run():
            try:
                fn()
            except PermissionError:
                root.after(0, lambda: messagebox.showerror("مشكلة", "شغّل البرنامج كـ Administrator (كليك يمين > Run as administrator)."))
            except Exception as e:  # noqa
                msg = str(e)
                root.after(0, lambda: messagebox.showerror("مشكلة", msg))
        threading.Thread(target=run, daemon=True).start()

    def do_scan():
        if st["vol"]:
            st["vol"].close()
        set_status("بقرا الفهرس...")
        v = Volume(drive.get())
        n = v.scan(set_prog)
        st["vol"] = v
        set_status("خلصت. لقيت %d ملف محذوف. اختار الفولدر ودوس ابحث." % len(v.files))
        do_folders()

    sort_state = {"col": "size", "rev": True}   # الافتراضي: الأكبر الأول

    def show_results():
        keys = {"status": lambda f: f.status, "size": lambda f: f.size or 0,
                "path": lambda f: f.path.lower(), "name": lambda f: f.name.lower()}
        st["res"].sort(key=keys[sort_state["col"]], reverse=sort_state["rev"])
        tree.delete(*tree.get_children())
        for f in st["res"][:3000]:
            tree.insert("", "end", values=(f.status, fmt_size(f.size or 0), f.path, f.name))

    def sort_by(col):
        if sort_state["col"] == col:
            sort_state["rev"] = not sort_state["rev"]
        else:
            sort_state["col"], sort_state["rev"] = col, (col == "size")
        show_results()

    def do_folders():
        v = st["vol"]
        if not v:
            return
        items = v.folder_summary(types_value())
        vals = ["%s   (%d ملف — %s — منهم %d فوق 100KB)" % (p or "<جذر البارتيشن>", c, fmt_size(sz), big)
                for p, c, sz, big in items]
        st["fmap"] = {vals[i]: items[i][0] for i in range(len(items))}
        root.after(0, lambda: fcombo.config(values=vals))

    def do_search():
        v = st["vol"]
        if not v:
            set_status("اقرا الفهرس الأول.")
            return
        folder = st.get("fmap", {}).get(fcombo.get(), fcombo.get())
        nm = name_e.get().strip()
        tv = types_value()
        res = v.search(folder, tv, skip_var.get())
        if nm:
            res = [f for f in res if nm.lower() in f.name.lower()]
        st["res"] = res
        tot = sum(f.size or 0 for f in res)
        big = sum(1 for f in res if (f.size or 0) >= 100 * 1024)

        def show():
            show_results()
            status.config(text="النتيجة: %d ملف (%s) — منهم %d فوق 100KB%s" % (
                len(res), fmt_size(tot), big, " — بعرض أول 3000 بس" if len(res) > 3000 else ""))
        root.after(0, show)

    def do_recover():
        v, res, d = st["vol"], st["res"], dest_e.get().strip()
        if not v or not res:
            set_status("مفيش نتايج.")
            return
        if not d:
            set_status("اختار فولدر الحفظ.")
            return
        if same_drive(d, drive.get()):
            root.after(0, lambda: messagebox.showerror("لأ", "الحفظ لازم يبقى على هارد غير اللي بتسترجع منه!"))
            return
        set_status("بسترجع...")
        ok, fail = run_recovery(v, res, d, tick=lambda a, b: (set_prog(a, b), set_status("استرجعت %d من %d" % (a, b))))
        set_status("تم: %d اتسترجع، %d متخطّى. راجع %s" % (ok, fail, d))

    btn_scan.config(command=lambda: work(do_scan))
    btn_folders.config(command=lambda: work(do_folders))
    btn_search.config(command=lambda: work(do_search))
    btn_rec.config(command=lambda: work(do_recover))
    root.mainloop()


# ----------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="استرجاع ملفات محذوفة من NTFS بقراءة الفهرس")
    ap.add_argument("--source", help="D: أو مسار ملف صورة")
    ap.add_argument("--folder", default="", help="جزء من مسار الفولدر")
    ap.add_argument("--types", default="", help='مثال: "*.jpg;*.mp4" أو اسم ملف')
    ap.add_argument("--dest", help="فولدر الحفظ (على هارد تاني)")
    ap.add_argument("--list", action="store_true", help="اعرض النتايج بس من غير استرجاع")
    ap.add_argument("--text", action="store_true", help="قوايم بالكتابة")
    a = ap.parse_args()
    if a.text:
        return text_mode(a)
    if not a.source:
        return gui_mode()
    vol = Volume(a.source)
    vol.scan(lambda x, y: print("\r  قراءة الفهرس %d%%" % (100 * x // max(y, 1)), end="", flush=True))
    print()
    res = vol.search(a.folder, a.types)
    print("لقيت %d ملف." % len(res))
    for f in res[:200]:
        print("[%s] %s\\%s  %s" % (f.status, f.path, f.name, fmt_size(f.size or 0)))
    if a.dest and not a.list:
        if same_drive(a.dest, a.source):
            sys.exit("الحفظ لازم يبقى على هارد غير المصدر.")
        ok, fail = run_recovery(vol, res, a.dest)
        print("تم: %d اتسترجع، %d متخطّى." % (ok, fail))
    vol.close()


if __name__ == "__main__":
    main()
