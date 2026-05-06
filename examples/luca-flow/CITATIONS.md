# Imagery citations

The AURORA microsite uses 12 NASA public-domain photographs and visualizations. Each is sourced from [images.nasa.gov](https://images.nasa.gov), credited per NASA's media-usage guidelines, and committed to this repository so the demo runs deterministically and offline.

## NASA media-usage guidelines

NASA still and motion imagery is generally not copyrighted and may be used for educational or informational purposes (including photo collections, textbooks, public exhibits, computer graphical simulations, and Internet web pages) without prior permission, provided NASA is acknowledged as the source. See:

- NASA media usage guidelines: <https://www.nasa.gov/multimedia/guidelines/index.html>
- NASA image and media usage: <https://www.nasa.gov/nasa-brand-center/images-and-media/>

This usage is non-commercial, educational, and clearly attributes NASA on every page where imagery appears.

## Master credit list

Each image below is attributed `Image credit: NASA` per the guidelines, with the originating NASA center where known. Per-image metadata (title, description, source URL, fetch provenance) is in [`assets/img/nasa/SOURCES.yaml`](assets/img/nasa/SOURCES.yaml).

The deployer renders a per-page citations footer from these two files at build time; this document is the long-form attribution that the footer's "view full citations" link points at.

| ID | Title | Credit |
|---|---|---|
| iss072e159172 | The aurora borealis blankets the Earth | NASA / JSC |
| iss072e709711 | The aurora borealis crowns Earth's horizon above Canada | NASA / JSC |
| iss072e188141 | A bright green aurora borealis streams above Earth's surface | NASA / JSC |
| iss072e451060 | A red and green aurora borealis above Canada's Gulf of St. Lawrence | NASA / JSC |
| iss072e820937 | Clouds swirl over the Gulf of Alaska underneath the aurora | NASA / JSC |
| iss029e012564 | Aurora Borealis and city lights on the horizon | NASA / JSC |
| iss072e083078 | The aurora australis streams over the Earth | NASA / JSC |
| iss040e040103 | Time lapse - Aurora Australis | NASA / JSC |
| iss072e011489 | The aurora australis blends with Earth's atmospheric glow | NASA / JSC |
| GSFC_20171208_Archive_e000614 | Nighttime View of Aurora Borealis | NASA / GSFC |
| GSFC_20171208_Archive_e001871 | NASA's IMAGE Spacecraft View of Aurora Australis from Space | NASA / GSFC |
| GSFC_20171208_Archive_e001111 | Magnetospheric Multiscale (MMS) | NASA / GSFC |

(Yes, this is the one place in the repo where a table is load-bearing, see `../../AGENTS.md` on tables-in-prose-vs-tables-in-data.)

## Mission references

The AURORA marketing copy references real NASA missions for flavor. The product is fictional; the missions are not.

- **THEMIS** (Time History of Events and Macroscale Interactions during Substorms) - five-spacecraft constellation studying auroral substorms and the magnetosphere. Launched 2007.
- **MMS** (Magnetospheric Multiscale Mission) - four-spacecraft constellation studying magnetic reconnection in the magnetosphere. Launched 2015. Imagery used on `science.html`.
- **IMAGE** (Imager for Magnetopause-to-Aurora Global Exploration) - magnetospheric imager, 2000-2005. Imagery used on `science.html`.
- **ISS Expedition crew Earth observations** - source of every photograph in the gallery.

## On the AURORA product

The AURORA desk lamp is a fictional consumer device created for this demo. There is no Vent Atelier, no SKU AURORA-1, no pre-order. The marketing copy is intentionally earnest and does not wink at the reader; the gap between the copy ("physically channels charged particles") and the physics of LEDs is the joke.
