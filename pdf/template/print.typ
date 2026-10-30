#let fitPrintImage(picture) = {
  layout(size => {
    let natural = measure(picture, width: size.width)
    image(
      picture.source,
      width: size.width,
      height: calc.min(natural.height, 205mm),
      fit: "contain",
      alt: picture.at("alt", default: none),
    )
  })
}

#let printAuthors(names, affiliations) = {
  set par(justify: false, leading: 0.35em, spacing: 5pt)
  text(size: 9.5pt, names)
  v(3pt)
  text(size: 8pt, affiliations)
  v(6pt)
}

#let printStudy(body) = {
  set text(size: 8.5pt)
  set par(justify: false)
  body
  v(10pt)
}

#let printNote(body, heading: none) = block(
  inset: (left: 7pt, top: 3pt, bottom: 3pt),
  stroke: (left: 0.7pt + luma(140)),
  below: 7pt,
  {
    set text(size: 8.5pt)
    set par(justify: false, spacing: 3pt)
    if heading != none { strong(heading); parbreak() }
    body
  },
)
