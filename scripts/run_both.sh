#!/bin/bash
# Render both films (people / arch) from segments through to encoding
set -e
cd "$(dirname "$0")/.."
B=/Applications/Blender.app/Contents/MacOS/Blender
for g in runner_solo arch1 arch2; do
  mkdir -p out/film/seg_$g; find out/film/seg_$g -name '*.png' -delete
  $B -b -P film_scene.py -- $g 2>&1 | grep -iE "error|Traceback" || true
  echo "seg $g $(ls out/film/seg_$g | wc -l)"
done
for f in people arch; do
  .venv/bin/python film_edit.py $f
  ln -sfn film/$f/base out/${f}base_frames
  rm -rf out/${f}base_cv
  .venv/bin/python analyze.py ${f}base > out/analyze_${f}.log 2>&1
  tail -1 out/analyze_${f}.log
  mkdir -p out/film/$f/final; find out/film/$f/final -name '*.png' -delete
  .venv/bin/python film_composite.py $f | tail -1
  ffmpeg -v error -y -framerate 30 -i out/film/$f/final/%04d.png -c:v libx264 -preset slow -crf 12 -pix_fmt yuv420p -tune grain -movflags +faststart out/film/tread_$f.mp4
  ffmpeg -v error -y -i out/film/tread_$f.mp4 -vf "select='not(mod(n\,12))',scale=200:-1,tile=10x5" -frames:v 1 out/film/_sheet_$f.jpg
  ls -la out/film/tread_$f.mp4
done
