"use client";

import "leaflet/dist/leaflet.css";

import { useEffect } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";

import type { Club, MapTiles } from "@/lib/clubs/types";

const COLORS = { club: "#7c3aed", sports_centre: "#0284c7", public_courts: "#059669" } as const;

function FitBounds({ clubs, center }: { clubs: Club[]; center: [number, number] }) {
  const map = useMap();
  useEffect(() => {
    if (clubs.length === 0) {
      map.setView(center, 11);
      return;
    }
    map.fitBounds(
      clubs.map((club) => [club.lat, club.lon] as [number, number]),
      { padding: [24, 24], maxZoom: 15 },
    );
  }, [clubs, center, map]);
  return null;
}

/** Leaflet caches its container size; re-measure when the layout changes (responsive grid,
 * rotation, sidebar), or tiles render only in part of the map. */
function TrackSize() {
  const map = useMap();
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return null;
}

function FocusSelected({ club }: { club: Club | undefined }) {
  const map = useMap();
  useEffect(() => {
    if (club) map.flyTo([club.lat, club.lon], Math.max(map.getZoom(), 14), { duration: 0.6 });
  }, [club, map]);
  return null;
}

/** Leaflet map (client-only). Circle markers avoid Leaflet's bundler-unfriendly icon images. */
export default function ClubMap({
  clubs,
  center,
  tiles,
  selectedId,
  onSelect,
}: {
  clubs: Club[];
  center: [number, number];
  tiles: MapTiles;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const selected = clubs.find((club) => club.id === selectedId);
  return (
    <MapContainer center={center} zoom={11} scrollWheelZoom className="h-full w-full" style={{ background: "#e5e7eb" }}>
      <TileLayer url={tiles.url} attribution={tiles.attribution} />
      <TrackSize />
      <FitBounds clubs={clubs} center={center} />
      <FocusSelected club={selected} />
      {clubs.map((club) => {
        const active = club.id === selectedId;
        return (
          <CircleMarker
            key={club.id}
            center={[club.lat, club.lon]}
            radius={active ? 10 : 6}
            pathOptions={{
              color: "#fff",
              weight: active ? 3 : 1.5,
              fillColor: COLORS[club.kind],
              fillOpacity: 0.95,
            }}
            eventHandlers={{ click: () => onSelect(club.id) }}
          >
            <Tooltip direction="top" offset={[0, -6]}>
              {club.name}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
