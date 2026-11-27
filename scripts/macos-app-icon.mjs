import { Buffer } from 'node:buffer';

export function isOfficeKitPackagedMacIcon(iconFile, bundledImages, expectedImages) {
  if (iconFile !== 'icon.icns' || !Array.isArray(bundledImages) ||
      !Array.isArray(expectedImages) || bundledImages.length < 1 ||
      bundledImages.length !== expectedImages.length) return false;
  return expectedImages.every(([name, expected]) => {
    const bundled = bundledImages.find(([bundledName]) => bundledName === name)?.[1];
    return Buffer.isBuffer(bundled) && Buffer.isBuffer(expected) && bundled.equals(expected);
  });
}
