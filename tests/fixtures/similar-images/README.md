# Similar-image real-photo fixtures

These are four small, EXIF-free derivatives of individual CC0 1.0 photographs. Their Commons file pages identify the authors and state CC0. Each fixture was orientation-corrected, reduced to at most 512 pixels on its longest edge, and re-encoded as JPEG without source metadata.

| Fixture | Source and author | License record |
| --- | --- | --- |
| `cc0/dog-portrait.jpg` | [Photo of a dog](https://commons.wikimedia.org/wiki/File:Photo_of_a_dog.jpg), ContaDeletada2906 | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `cc0/dog-on-road.jpg` | [Dog on dirt road](https://commons.wikimedia.org/wiki/File:Dog_on_dirt_road.jpg), Arlo Barnes | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `cc0/dandelion.jpg` | [Dandelion flower photo](https://commons.wikimedia.org/wiki/File:Dandelion_flower_photo.jpg), LorelMan | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `cc0/landscape.jpg` | [A lush verdant landscape](https://commons.wikimedia.org/wiki/File:A_lush_verdant_landscape.jpg), Ayyuha Sideeq | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

`test_cc0_photographs_group_realistic_variants_without_cross_scene_matches` derives six reproducible variants from each photo: +20% exposure with JPEG recompression, a 20% center crop/zoom, an off-center crop/zoom, a 7×5 px camera translation, a 5° rotation, and JPEG quality 35. It checks 24/24 derived near-duplicates are grouped with their source and that the four unrelated scenes remain separate; two scenes both depict dogs, which gives the false-positive check a similar-subject control.

These transformed stills test the matcher on genuine photographic texture, but they are not real camera burst sequences. They do not establish general burst recall or precision. Keep that limitation explicit until a suitably licensed ground-truth burst corpus is available.
