# Extras

Not part of the build.

`after_action_reports.txt` is the classified annex that padded our first
release to exactly 7.62 MB. It is a roast of milsim regulars and does nothing in
game. To ship it inside the PBO, copy it to `addons/main/classified/` before
`hemtt build`. HEMTT binarizes the config, so the PBO won't land on 7.62 MB
again; the squad lead will have to stand by at a different size.
