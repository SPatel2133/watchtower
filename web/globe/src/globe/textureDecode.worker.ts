/// <reference lib="webworker" />
/**
 * Decodes the 4k Earth maps off the main thread. The main thread fetches the file and posts the Blob; this worker
 * decodes it with createImageBitmap (flipped vertically, so the bitmap matches three's flipY=true image textures
 * of the 1k set) and transfers the bitmap back. The main thread only uploads it.
 */
const ctx = self as unknown as DedicatedWorkerGlobalScope

ctx.onmessage = async (ev: MessageEvent<{ id: number; blob: Blob }>) => {
  const { id, blob } = ev.data
  try {
    const bitmap = await createImageBitmap(blob, { imageOrientation: 'flipY', premultiplyAlpha: 'none', colorSpaceConversion: 'none' })
    ctx.postMessage({ id, bitmap }, [bitmap])
  } catch (err) {
    ctx.postMessage({ id, error: err instanceof Error ? err.message : String(err) })
  }
}
