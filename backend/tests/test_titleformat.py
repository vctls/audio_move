import pytest

from app.titleformat import Context, format_track

TAGS = {
    "ARTIST": ["Daft Punk"],
    "ALBUM": ["Discovery"],
    "DATE": ["2001-03-12"],
    "TRACKNUMBER": ["3"],
    "TOTALTRACKS": ["14"],
    "TITLE": ["Digital Love"],
    "GENRE": ["House", "French Touch"],
}
INFO = {"codec": "FLAC", "length": 301.4, "channels": 2, "samplerate": 44100, "filesize": 2048}


def fmt(template, tags=TAGS, info=INFO, path="/music/in/03 digital love.flac", **kw):
    return format_track(template, Context(tags, info, path, **kw))


@pytest.mark.parametrize(
    "template,expected",
    [
        ("%artist% - %title%", "Daft Punk - Digital Love"),
        ("%album artist%", "Daft Punk"),
        ("%tracknumber%", "03"),
        ("%track number%", "3"),
        ("%year%", "2001"),
        ("%codec%", "FLAC"),
        ("$caps(%codec%)", "Flac"),
        ("'['$caps(%codec%)']'", "[Flac]"),
        ("[%codec%]", "FLAC"),
        ("[%discnumber%.]%tracknumber%", "03"),
        ("[(%comment%)]", ""),
        ("%comment%", "?"),
        ("%genre%", "House, French Touch"),
        ("$meta(genre,1)", "French Touch"),
        ("$meta_sep(genre,' / ')", "House / French Touch"),
        ("$meta_num(genre)", "2"),
        ("$if(%comment%,yes,no)", "no"),
        ("$if(%title%,yes)", "yes"),
        ("$if2(%comment%,none)", "none"),
        ("$if3(%comment%,%foo%,%title%,x)", "Digital Love"),
        ("$ifgreater(%tracknumber%,2,big,small)", "big"),
        ("$ifequal(%totaltracks%,14,full,partial)", "full"),
        ("$iflonger(%title%,5,long,short)", "long"),
        ("$select(2,a,b,c)", "b"),
        ("$add(1,2,3)", "6"),
        ("$sub(10,3)", "7"),
        ("$div(7,2)", "3"),
        ("$mod(-7,3)", "-1"),
        ("$muldiv(10,3,4)", "8"),
        ("$num(%tracknumber%,3)", "003"),
        ("$num(-123,5)", "-0123"),
        ("$num(A1,3)", "000"),
        ("$left(%title%,3)$right(%title%,4)", "DigLove"),
        ("$cut(abc,-1)", "abc"),
        ("$pad(ab,4,_)|$pad_right(ab,4)", "ab__|  ab"),
        ("$padcut(abcdef,3)", "abc"),
        ("$replace(ab,a,b,b,c)", "bc"),
        ("$lower(%artist%)$upper(x)", "daft punkX"),
        ("$caps2(mcCARTNEY paul)", "McCARTNEY Paul"),
        ("$abbr('This is a Long Title (12-inch version) [needs tags]')", "TiaLT1v[needst"),
        ("$roman(1994)", "MCMXCIV"),
        ("$rot13(foobar2000)", "sbbone2000"),
        ("$strchr(abca,a)$strrchr(abca,a)$strstr(abc,bc)", "142"),
        ("$substr(abcdef,2,4)", "bcd"),
        ("$insert(abc,X,1)", "aXbc"),
        ("$len(%title%)", "12"),
        ("$trim(  x  )", "x"),
        ("$stripprefix(The Beatles)|$swapprefix(The Beatles)", "Beatles|Beatles, The"),
        ("$ascii(Björk Guðmundsdóttir)", "Bjork Gu?mundsdottir"),
        ("$year(%date%)-$month(%date%)", "2001-03"),
        ("$put(x,1)$get(x)$puts(y,2)$get(y)", "112"),
        ("$directory(%path%)|$ext(%path%)|$filename(%path%)", "in|flac|03 digital love"),
        ("%filename%|%filename_ext%|%directoryname%", "03 digital love|03 digital love.flac|in"),
        ("%length%|%length_seconds%", "5:01|301"),
        ("%channels%|%samplerate%", "stereo|44100"),
        ("$and(%title%,%artist%)$if($or(%x%,%title%),T,F)$if($not(%x%),T,F)", "TT"),
        ("$if($strcmp(a,a),T,F)$if($stricmp(A,a),T,F)$if($greater(2,1),T,F)", "TTT"),
        ("$longest(a,abc,ab)$shortest(abc,b,cd)", "abcb"),
        ("a'%'b''c", "a%b'c"),
        ("x$nope(1)", "x[UNKNOWN FUNCTION]"),
        ("$if(1)", "[INVALID $IF SYNTAX]"),
        ("// comment\n%title%\n", "Digital Love"),
        ("(%title%), done", "(Digital Love), done"),
    ],
)
def test_format(template, expected):
    assert fmt(template) == expected


def test_remappings():
    tags = {"ARTIST": ["Track Artist"], "ALBUM ARTIST": ["Various Artists"], "TITLE": ["T"]}
    assert fmt("%album artist%|%artist%|%track artist%", tags=tags) == (
        "Various Artists|Track Artist|Track Artist"
    )
    assert fmt("[%track artist%]", tags={"ARTIST": ["A"]}) == ""
    assert fmt("%artist%", tags={"COMPOSER": ["Bach"]}) == "Bach"
    assert fmt("%title%", tags={}) == "03 digital love"
    assert fmt("%year%", tags={"YEAR": ["1999"], "DATE": ["2001"]}) == "1999"


def test_tracknumber_padding_rules():
    for raw, padded in [("5", "05"), ("05", "05"), ("104", "104"), ("A3", "A3"), ("-", "-")]:
        assert fmt("%tracknumber%", tags={"TRACKNUMBER": [raw]}) == padded


def test_field_filter_applies_to_fields_only():
    out = fmt("%artist%/x", tags={"ARTIST": ["AC/DC"]}, field_filter=lambda v: v.replace("/", "_"))
    assert out == "AC_DC/x"
