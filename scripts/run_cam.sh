#!/bin/bash
# Bolder camera: re-render only the scene segments (morphs unchanged), rebuild both films → tread_*_morph_cam.mp4
cd "$(dirname "$0")/.."
B=/Applications/Blender.app/Contents/MacOS/Blender
for g in walker2 greenhouse2 runner2 plat3 gates3 corr3 esc3 rev3; do
  find out/film/seg_$g -name '*.png' -delete
  $B -b -P film_scene.py -- $g 2>&1 | grep -iE "error|Traceback"
  echo "seg $g $(ls out/film/seg_$g | wc -l)"
done
for f in people arch; do
  .venv/bin/python film_edit.py $f
  rm -rf out/${f}base_cv
  .venv/bin/python analyze.py ${f}base > out/analyze_${f}.log 2>&1
  tail -1 out/analyze_${f}.log
  find out/film/$f/final -name '*.png' -delete
  .venv/bin/python film_composite.py $f | tail -1
  ffmpeg -v error -y -framerate 30 -i out/film/$f/final/%04d.png -c:v libx264 -preset slow -crf 12 -pix_fmt yuv420p -tune grain -movflags +faststart out/film/tread_${f}_morph_cam.mp4
  ffmpeg -v error -y -i out/film/tread_${f}_morph_cam.mp4 -vf "select='not(mod(n\,14))',scale=200:-1,tile=10x6" -frames:v 1 out/film/_sheet_${f}_cam.jpg
  ls -la out/film/tread_${f}_morph_cam.mp4
done
