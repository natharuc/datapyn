import type { Rectangle } from "@glideapps/glide-data-grid";

/** Reserve a distinct sort target next to Glide's own header menu target. */
export function headerSortBounds(header: Rectangle, menu: Rectangle): Rectangle | undefined {
  if (header.width < 84) return;
  const menuOnLeft = menu.x < header.x + header.width / 2;
  return { x: menuOnLeft ? menu.x + menu.width : menu.x - 24, y: header.y, width: 24, height: header.height };
}

export function containsHeaderPoint(bounds: Rectangle | undefined, x: number, y: number): boolean {
  return !!bounds && x >= bounds.x && x < bounds.x + bounds.width && y >= bounds.y && y < bounds.y + bounds.height;
}
