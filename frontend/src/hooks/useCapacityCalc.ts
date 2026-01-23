/**
 * useCapacityCalc Hook
 *
 * React hook for capacity and focus factor calculations.
 * Extracted from CapacitySettingsPanel business logic.
 */

import { useCallback, useMemo } from 'react';

/** MUI color palette type for capacity indicators */
export type CapacityColor = 'success' | 'warning' | 'error' | 'default';

/** Focus factor thresholds */
export const FOCUS_FACTOR_THRESHOLDS = {
  good: 0.75,
  acceptable: 0.6,
  min: 0.5,
  max: 1.0,
} as const;

/** Utilization thresholds */
export const UTILIZATION_THRESHOLDS = {
  overloaded: 100,
  nearCapacity: 80,
} as const;

/** Default capacity settings */
export const DEFAULT_CAPACITY = {
  hoursPerWeek: 40,
  focusFactor: 0.8,
} as const;

/**
 * Calculate color based on focus factor value.
 * @param focusFactor Value between 0 and 1
 * @returns MUI color: success (>=0.75), warning (>=0.6), error (<0.6)
 */
export function getFocusFactorColor(focusFactor: number): CapacityColor {
  if (focusFactor >= FOCUS_FACTOR_THRESHOLDS.good) return 'success';
  if (focusFactor >= FOCUS_FACTOR_THRESHOLDS.acceptable) return 'warning';
  return 'error';
}

/**
 * Calculate focus factor as a percentage (0-100).
 * @param focusFactor Value between 0 and 1
 * @returns Integer percentage
 */
export function focusFactorToPercent(focusFactor: number): number {
  return Math.round(focusFactor * 100);
}

/**
 * Calculate effective capacity based on hours and focus factor.
 * @param hoursPerWeek Theoretical hours available
 * @param focusFactor Focus factor (0-1)
 * @returns Effective productive hours
 */
export function calculateEffectiveCapacity(
  hoursPerWeek: number,
  focusFactor: number
): number {
  return hoursPerWeek * focusFactor;
}

/**
 * Calculate utilization percentage.
 * @param used Hours or story points used
 * @param capacity Total available capacity
 * @returns Utilization percentage (0-100+)
 */
export function calculateUtilization(used: number, capacity: number): number {
  if (capacity <= 0) return 0;
  return Math.round((used / capacity) * 100);
}

/**
 * Get color for utilization percentage.
 * @param percentage Utilization percentage
 * @returns MUI color: error (>=100%), warning (>=80%), success (<80%)
 */
export function getUtilizationColor(percentage: number): CapacityColor {
  if (percentage >= UTILIZATION_THRESHOLDS.overloaded) return 'error';
  if (percentage >= UTILIZATION_THRESHOLDS.nearCapacity) return 'warning';
  return 'success';
}

/**
 * Get color for hours per week setting.
 * @param hoursPerWeek Weekly hours
 * @returns 'warning' if part-time (<40h), 'default' otherwise
 */
export function getHoursColor(hoursPerWeek: number): CapacityColor {
  return hoursPerWeek < DEFAULT_CAPACITY.hoursPerWeek ? 'warning' : 'default';
}

/** Capacity calculation results */
export interface CapacityCalculation {
  effectiveCapacity: number;
  focusFactorPercent: number;
  focusFactorColor: CapacityColor;
}

/** Utilization calculation results */
export interface UtilizationCalculation {
  percentage: number;
  color: CapacityColor;
  cappedPercentage: number;
}

/** Team capacity summary calculations */
export interface TeamCapacityCalculation {
  totalTheoretical: number;
  totalEffective: number;
  averageFocusFactor: number;
  memberCount: number;
}

/** Member capacity data for team calculations */
export interface MemberCapacity {
  hoursPerWeek: number;
  focusFactor: number;
}

/**
 * Hook for capacity and focus factor calculations.
 *
 * @example
 * ```tsx
 * const { calcCapacity, calcUtilization, getFocusColor, getUtilColor } = useCapacityCalc();
 *
 * // Calculate effective capacity
 * const { effectiveCapacity, focusFactorPercent, focusFactorColor } = calcCapacity(40, 0.8);
 * // Result: { effectiveCapacity: 32, focusFactorPercent: 80, focusFactorColor: 'success' }
 *
 * // Calculate utilization
 * const { percentage, color, cappedPercentage } = calcUtilization(35, 32);
 * // Result: { percentage: 109, color: 'error', cappedPercentage: 100 }
 * ```
 */
export function useCapacityCalc() {
  /**
   * Calculate capacity metrics for a member.
   */
  const calcCapacity = useCallback(
    (hoursPerWeek: number, focusFactor: number): CapacityCalculation => ({
      effectiveCapacity: calculateEffectiveCapacity(hoursPerWeek, focusFactor),
      focusFactorPercent: focusFactorToPercent(focusFactor),
      focusFactorColor: getFocusFactorColor(focusFactor),
    }),
    []
  );

  /**
   * Calculate utilization metrics.
   */
  const calcUtilization = useCallback(
    (used: number, capacity: number): UtilizationCalculation => {
      const percentage = calculateUtilization(used, capacity);
      return {
        percentage,
        color: getUtilizationColor(percentage),
        cappedPercentage: Math.min(percentage, 100),
      };
    },
    []
  );

  /**
   * Calculate team-wide capacity summary.
   */
  const calcTeamCapacity = useCallback(
    (members: MemberCapacity[], sprintWeeks: number = 2): TeamCapacityCalculation => {
      if (members.length === 0) {
        return {
          totalTheoretical: 0,
          totalEffective: 0,
          averageFocusFactor: 0,
          memberCount: 0,
        };
      }

      const totalTheoretical = members.reduce(
        (sum, m) => sum + m.hoursPerWeek * sprintWeeks,
        0
      );
      const totalEffective = members.reduce(
        (sum, m) => sum + calculateEffectiveCapacity(m.hoursPerWeek, m.focusFactor) * sprintWeeks,
        0
      );
      const averageFocusFactor =
        members.reduce((sum, m) => sum + m.focusFactor, 0) / members.length;

      return {
        totalTheoretical,
        totalEffective,
        averageFocusFactor,
        memberCount: members.length,
      };
    },
    []
  );

  /**
   * Format effective capacity for display.
   * @param hoursPerWeek Theoretical hours
   * @param focusFactor Focus factor (0-1)
   * @returns Formatted string like "32.0h/week"
   */
  const formatEffectiveCapacity = useCallback(
    (hoursPerWeek: number, focusFactor: number): string => {
      const effective = calculateEffectiveCapacity(hoursPerWeek, focusFactor);
      return `${effective.toFixed(1)}h/week`;
    },
    []
  );

  /**
   * Format capacity breakdown for display.
   * @param hoursPerWeek Theoretical hours
   * @param focusFactor Focus factor (0-1)
   * @returns Formatted string like "40h x 80% focus"
   */
  const formatCapacityBreakdown = useCallback(
    (hoursPerWeek: number, focusFactor: number): string => {
      return `${hoursPerWeek}h x ${focusFactorToPercent(focusFactor)}% focus`;
    },
    []
  );

  return {
    // Calculation functions
    calcCapacity,
    calcUtilization,
    calcTeamCapacity,

    // Color getters (for direct use)
    getFocusColor: getFocusFactorColor,
    getUtilColor: getUtilizationColor,
    getHoursColor,

    // Formatting helpers
    formatEffectiveCapacity,
    formatCapacityBreakdown,
    focusToPercent: focusFactorToPercent,

    // Constants
    thresholds: {
      focusFactor: FOCUS_FACTOR_THRESHOLDS,
      utilization: UTILIZATION_THRESHOLDS,
    },
    defaults: DEFAULT_CAPACITY,
  };
}

/**
 * Hook for single capacity setting state.
 * Provides memoized calculations for a specific hours/focus combination.
 *
 * @example
 * ```tsx
 * const { effectiveCapacity, focusPercent, focusColor, breakdown } = useCapacityValue(40, 0.8);
 * ```
 */
export function useCapacityValue(hoursPerWeek: number, focusFactor: number) {
  const effectiveCapacity = useMemo(
    () => calculateEffectiveCapacity(hoursPerWeek, focusFactor),
    [hoursPerWeek, focusFactor]
  );

  const focusPercent = useMemo(
    () => focusFactorToPercent(focusFactor),
    [focusFactor]
  );

  const focusColor = useMemo(
    () => getFocusFactorColor(focusFactor),
    [focusFactor]
  );

  const hoursColor = useMemo(
    () => getHoursColor(hoursPerWeek),
    [hoursPerWeek]
  );

  const formatted = useMemo(
    () => `${effectiveCapacity.toFixed(1)}h/week`,
    [effectiveCapacity]
  );

  const breakdown = useMemo(
    () => `${hoursPerWeek}h x ${focusPercent}% focus`,
    [hoursPerWeek, focusPercent]
  );

  return {
    effectiveCapacity,
    focusPercent,
    focusColor,
    hoursColor,
    formatted,
    breakdown,
  };
}

export default useCapacityCalc;
