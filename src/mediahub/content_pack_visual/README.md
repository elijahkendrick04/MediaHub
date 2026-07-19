# content_pack_visual

Attaches the rendered pictures to the right items in a content pack, so the
download has both the captions and the images together.

`visual_index.py` keeps a tiny lookup table (id of a picture → which run and
folder it lives in) so the web page can fetch a picture in one step instead of
searching through every run's folder. New pictures get added to the table when
they're saved; older ones get added the first time they're opened.
