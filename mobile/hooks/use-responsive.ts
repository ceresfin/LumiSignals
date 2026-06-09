import { useWindowDimensions } from 'react-native';

// Wide = iPad (portrait ~768) or a phone in landscape (~840+). Below this we
// keep the original full-width phone layout untouched.
const WIDE_BREAKPOINT = 700;
// On wide screens, cap content to a readable centered column instead of
// stretching cards/forms edge-to-edge across an iPad / landscape display.
const CONTENT_MAX_WIDTH = 820;

/**
 * Responsive sizing that updates live on rotation (useWindowDimensions).
 *
 * `contentStyle` is meant to be merged into a ScrollView/FlatList
 * `contentContainerStyle`. On wide screens it centers content in a readable
 * column via symmetric horizontal padding — NOT maxWidth/alignSelf, which
 * would shrink the scroll/touch region to the column and break dragging from
 * the side margins. The content container stays full-width so scrolling works
 * edge-to-edge. On phones it's `undefined` (no change).
 */
export function useResponsive() {
  const { width, height } = useWindowDimensions();
  const isWide = width >= WIDE_BREAKPOINT;
  const isLandscape = width > height;
  const sidePad = Math.max(0, (width - CONTENT_MAX_WIDTH) / 2);
  const contentStyle = isWide && sidePad > 0
    ? { paddingHorizontal: sidePad }
    : undefined;
  return { width, height, isWide, isLandscape, contentStyle };
}
