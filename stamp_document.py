"""Lossless image input and placement of a stamp on a document."""
from io import BytesIO
import warnings
from PIL import Image, ImageOps


def read_document(raw, max_mb=12):
    if len(raw) > max_mb*1024*1024:
        raise ValueError(f"Изображение должно быть не больше {max_mb} МБ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as im:
                if im.width*im.height > 40_000_000 or min(im.size)<16:
                    raise ValueError("Размер изображения: от 16 пикселей, не больше 40 мегапикселей")
                return ImageOps.exif_transpose(im).convert("RGBA")
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Не получилось прочитать изображение. Пришли PNG, JPEG или WEBP") from None


def place_stamp(document, stamp, position=8, percent=25):
    if position not in range(9) or percent not in (15,25,35,45):
        raise ValueError("Выбери место и размер кнопками")
    out=document.convert("RGBA").copy()
    margin=max(1,round(min(out.size)*.03))
    width=max(1,min(round(out.width*percent/100),out.width-2*margin))
    stamp=ImageOps.contain(stamp,(width,max(1,out.height-2*margin)),Image.Resampling.LANCZOS)
    col,row=position%3,position//3
    x=round(margin+(out.width-2*margin-stamp.width)*col/2)
    y=round(margin+(out.height-2*margin-stamp.height)*row/2)
    out.alpha_composite(stamp,(x,y))
    return out
