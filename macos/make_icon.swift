// Draws Dico's app icon and writes build/Dico.iconset + Dico.icns.
//
// The mark is « é » — the accented letter, because typing accents is exactly
// what the tool spares you — set on a warm cream page over a squircle that
// runs from French blue to a soft rose. A folded page corner and a thin ruled
// line say « dictionary » without drawing a whole book, which turns to mush at
// 32 pt.
//
//   xcrun swift make_icon.swift            → build/Dico.icns (+ preview PNG)
import AppKit

let sizes: [Int] = [16, 32, 64, 128, 256, 512, 1024]
let outDir = "build/Dico.iconset"
try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

func lerp(_ a: CGFloat, _ b: CGFloat, _ t: CGFloat) -> CGFloat { a + (b - a) * t }

func draw(size S: CGFloat) -> NSImage {
    let image = NSImage(size: NSSize(width: S, height: S))
    image.lockFocus()
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.setAllowsAntialiasing(true)

    // macOS icons sit inside the canvas with a margin; the squircle is ~0.82 of it.
    let inset = S * 0.09
    let rect = CGRect(x: inset, y: inset, width: S - 2 * inset, height: S - 2 * inset)
    let radius = rect.width * 0.2237                     // the Big Sur squircle ratio
    let squircle = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)

    // Background: French blue → violet → rose, top-left to bottom-right.
    ctx.saveGState()
    squircle.addClip()
    let bg = NSGradient(colors: [NSColor(srgbRed: 0.13, green: 0.36, blue: 0.92, alpha: 1),
                                NSColor(srgbRed: 0.35, green: 0.36, blue: 0.94, alpha: 1),
                                NSColor(srgbRed: 0.62, green: 0.38, blue: 0.90, alpha: 1),
                                NSColor(srgbRed: 0.95, green: 0.47, blue: 0.58, alpha: 1)],
                        atLocations: [0, 0.38, 0.72, 1],
                        colorSpace: .sRGB)!
    bg.draw(in: rect, angle: -55)

    // A soft highlight in the upper left. Drawn over the WHOLE square: a
    // smaller rectangle leaves a visible seam where the gradient stops.
    let glow = NSGradient(starting: NSColor(white: 1, alpha: 0.26),
                          ending: NSColor(white: 1, alpha: 0))!
    glow.draw(in: rect, relativeCenterPosition: CGPoint(x: -0.45, y: 0.5))
    ctx.restoreGState()

    // At 16 pt the page and the letter fight over the same ten pixels. The
    // small sizes drop the page: a white « é » straight on the gradient is the
    // most legible thing that still reads as the same icon.
    let small = S <= 32
    if small {
        // Sized off the line box, not the point size: « é » is taller than it
        // looks and the accent was being clipped by the squircle.
        let fs = rect.height * 0.58
        let mark = NSAttributedString(string: "é", attributes: [
            .font: NSFont.systemFont(ofSize: fs, weight: .heavy),
            .foregroundColor: NSColor.white,
        ])
        let ms = mark.size()
        mark.draw(at: CGPoint(x: rect.midX - ms.width / 2,
                              y: rect.midY - ms.height / 2))
        image.unlockFocus()
        return image
    }

    // The page: a cream card, tilted a touch.
    let pw = rect.width * 0.56, ph = rect.height * 0.66
    ctx.saveGState()
    ctx.translateBy(x: rect.midX, y: rect.midY)
    ctx.rotate(by: -5 * .pi / 180)
    let page = CGRect(x: -pw / 2, y: -ph / 2, width: pw, height: ph)
    let pagePath = NSBezierPath(roundedRect: page, xRadius: pw * 0.10, yRadius: pw * 0.10)
    ctx.setShadow(offset: CGSize(width: 0, height: -S * 0.012), blur: S * 0.05,
                  color: NSColor(white: 0, alpha: 0.28).cgColor)
    NSColor(srgbRed: 0.99, green: 0.98, blue: 0.95, alpha: 1).setFill()
    pagePath.fill()
    ctx.setShadow(offset: .zero, blur: 0, color: nil)

    // One ruled line under the letter — the hint that this is an entry.
    let ruleY = page.minY + ph * 0.20
    NSColor(srgbRed: 0.29, green: 0.42, blue: 0.93, alpha: 0.28).setFill()
    NSBezierPath(roundedRect: CGRect(x: page.minX + pw * 0.20, y: ruleY,
                                     width: pw * 0.60, height: max(1, S * 0.016)),
                 xRadius: S * 0.01, yRadius: S * 0.01).fill()

    // « é », the mark itself.
    let fontSize = ph * 0.62
    let font = NSFont.systemFont(ofSize: fontSize, weight: .bold)
    let letter = NSAttributedString(string: "é", attributes: [
        .font: font,
        .foregroundColor: NSColor(srgbRed: 0.16, green: 0.20, blue: 0.42, alpha: 1),
    ])
    let ls = letter.size()
    letter.draw(at: CGPoint(x: -ls.width / 2,
                            y: ruleY + ph * 0.06 - fontSize * 0.09))
    ctx.restoreGState()
    image.unlockFocus()
    return image
}

func png(_ image: NSImage, _ path: String) {
    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let data = rep.representation(using: .png, properties: [:]) else { return }
    try? data.write(to: URL(fileURLWithPath: path))
}

for s in sizes {
    let img = draw(size: CGFloat(s))
    png(img, "\(outDir)/icon_\(s)x\(s).png")
    if s > 16 { png(draw(size: CGFloat(s)), "\(outDir)/icon_\(s / 2)x\(s / 2)@2x.png") }
}
png(draw(size: 512), "build/icon-preview.png")

let p = Process()
p.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
p.arguments = ["-c", "icns", outDir, "-o", "build/Dico.icns"]
try? p.run(); p.waitUntilExit()
print(p.terminationStatus == 0 ? "✓ build/Dico.icns" : "✗ iconutil failed")
