# Licensed animation clips (per installation, not in git)

Clips whose licence allows USE in the game but not redistribution of the raw
files: Mixamo downloads (Adobe terms), bought mocap packs (Fab, Unity Asset
Store, MoCap Online, ActorCore, …). Same layout and same rules as the free
library next door (`../clips/README.md`): `[<set>/]<kind>[_<n>].fbx`, Mixamo
rig, "Without Skin", movement clips "In Place", pairs as `<kind>__a/__b`.

Both libraries are read by the server (`GET /assets/animation-clips`); a file
with the same `[<set>/]<name>` in both resolves to THIS one — whoever installs
a premium pack wants it played. Nothing in here is tracked except this file;
the installation owner is responsible for the licence of what lies here.
