from upscaler import analysis

from tests.patterns import gradient, periodic


def test_verdicts():
    assert analysis.seam_report(periodic(200, 200)).verdict == "seamless"
    assert analysis.seam_report(gradient()).verdict == "composition"
    # Cut mid-repeat: the edges no longer wrap, but the repeat is still there.
    repeating = analysis.seam_report(periodic(230, 230))
    assert repeating.verdict == "repeating"
    # Autocorrelation is within a pixel; the tile search refines it.
    assert abs(repeating.periods_h[0][0] - 50) <= 1
    assert abs(repeating.periods_v[0][0] - 50) <= 1


def test_extract_tile_finds_the_repeat():
    img = periodic(230, 230)
    tile = analysis.extract_tile(img, analysis.seam_report(img))
    assert tile.box[2:] == (50, 50)
    assert tile.good
    lr, tb = analysis.seam_scores(analysis.to_rgb_array(tile.tile))
    assert lr < 2 and tb < 2


def test_extract_tile_refuses_composition():
    img = gradient()
    try:
        analysis.extract_tile(img, analysis.seam_report(img))
    except analysis.AnalysisError as exc:
        assert "No repeat" in str(exc)
    else:
        raise AssertionError("expected AnalysisError")


def test_large_image_analysed_downscaled():
    img = periodic(2500, 2000)
    report = analysis.seam_report(img)
    assert report.scale < 1
    assert report.verdict == "seamless"


def test_crop_boxes_and_pad():
    assert analysis.wrap_pad(periodic(100, 80)).size == (164, 144)
    assert analysis.crop_box("wrap", (100, 80), 4) == (128, 128, 528, 448)
    assert analysis.crop_box("tile", (50, 40), 2) == (100, 80, 200, 160)
    assert analysis.crop_box("plain", (50, 40), 2) is None


def test_proof_stays_small():
    proof = analysis.proof(periodic(4000, 3000), 2)
    assert max(proof.size) <= 1200
