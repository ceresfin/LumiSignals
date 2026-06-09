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
 * `contentContainerStyle`: on wide screens it caps the content to a centered
 * column; on phones it's `undefined` (no change).
 */
export function useResponsive() {
  const { width, height } = useWindowDimensions();
  const isWide = width >= WIDE_BREAKPOINT;
  const isLandscape = width > height;
  const contentStyle = isWide
    ? { maxWidth: CONTENT_MAX_WIDTH, width: '100%' as const, alignSelf: 'center' as const }
    : undefined;
  return { width, height, isWide, isLandscape, contentStyle };
}
