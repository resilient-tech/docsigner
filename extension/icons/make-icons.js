// Writes placeholder icons (solid blue squares) as icon16/48/128.png.
// Run once: node make-icons.js
// ponytail: solid color placeholders, replace with real artwork before store submission.

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");

const COLOR = [26, 86, 219, 255]; // same blue as the consent Allow button

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(zlib.crc32(body));
  return Buffer.concat([length, body, crc]);
}

function png(size) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); // width
  ihdr.writeUInt32BE(size, 4); // height
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 6;  // color type: RGBA
  // bytes 10-12: compression, filter, interlace, all 0

  const raw = Buffer.alloc(size * (1 + size * 4)); // each row: filter byte + pixels
  for (let y = 0; y < size; y++) {
    const row = y * (1 + size * 4) + 1;
    for (let x = 0; x < size; x++) raw.set(COLOR, row + x * 4);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

for (const size of [16, 48, 128]) {
  const file = path.join(__dirname, `icon${size}.png`);
  fs.writeFileSync(file, png(size));
  console.log("wrote", file);
}
