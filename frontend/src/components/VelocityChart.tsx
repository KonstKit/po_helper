import React from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ChartOptions,
  type ChartDataset,
} from 'chart.js';
import annotationPlugin from 'chartjs-plugin-annotation';

// Register the annotation plugin and required chart elements
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  annotationPlugin
);

export interface VelocityDataPoint {
  label: string;
  value: number;
  annotation?: string; // Optional annotation (e.g., "Sprint with vacation")
}

export interface VelocityChartProps {
  data: VelocityDataPoint[];
  targetVelocity?: number; // Target velocity line
  showTrend?: boolean; // Show trend line (linear regression)
  height?: number;
}

/**
 * Enhanced Velocity Chart with:
 * - Target velocity line (dashed horizontal line)
 * - Trend line (linear regression showing trajectory)
 * - Annotations for special events (e.g., sprints with vacations)
 * - Improved tooltips with context
 */
const VelocityChart: React.FC<VelocityChartProps> = ({
  data,
  targetVelocity,
  showTrend = true,
  height = 300,
}) => {
  // Calculate linear regression for trend line
  const calculateTrendLine = (values: number[]): number[] => {
    const n = values.length;
    if (n < 2) return values;

    let sumX = 0;
    let sumY = 0;
    let sumXY = 0;
    let sumXX = 0;

    values.forEach((y, x) => {
      sumX += x;
      sumY += y;
      sumXY += x * y;
      sumXX += x * x;
    });

    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    return values.map((_, x) => slope * x + intercept);
  };

  const values = data.map((d) => d.value);
  const labels = data.map((d) => d.label);
  const trendValues = showTrend ? calculateTrendLine(values) : [];

  // Build datasets
  const datasets: ChartDataset<'line', number[]>[] = [
    {
      label: 'Actual Velocity (h)',
      data: values,
      borderColor: 'rgb(75, 192, 192)',
      backgroundColor: 'rgba(75, 192, 192, 0.2)',
      borderWidth: 3,
      pointRadius: 6,
      pointHoverRadius: 8,
      tension: 0.2, // Smooth curve
      fill: true,
    },
  ];

  // Add trend line if enabled
  if (showTrend && trendValues.length > 0) {
    const trend = trendValues[trendValues.length - 1] - trendValues[0];
    const trendDirection = trend > 0 ? 'Improving' : trend < 0 ? 'Declining' : 'Stable';

    datasets.push({
      label: `Trend (${trendDirection})`,
      data: trendValues,
      borderColor: trend > 0 ? 'rgba(76, 175, 80, 0.8)' : 'rgba(244, 67, 54, 0.8)',
      borderDash: [8, 4],
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 0,
      fill: false,
    });
  }

  // Build annotations
  const annotations: Record<string, unknown> = {};

  // Target line annotation
  if (targetVelocity !== undefined) {
    annotations.targetLine = {
      type: 'line',
      yMin: targetVelocity,
      yMax: targetVelocity,
      borderColor: 'rgba(255, 159, 64, 0.9)',
      borderWidth: 2,
      borderDash: [10, 5],
      label: {
        display: true,
        content: `Target: ${targetVelocity}h`,
        position: 'end',
        backgroundColor: 'rgba(255, 159, 64, 0.9)',
        color: 'white',
        font: {
          size: 12,
          weight: 'bold',
        },
        padding: 4,
      },
    };
  }

  // Add point annotations for special events
  data.forEach((point, index) => {
    if (point.annotation) {
      annotations[`point_${index}`] = {
        type: 'point',
        xValue: index,
        yValue: point.value,
        backgroundColor: 'rgba(255, 99, 132, 0.8)',
        borderColor: 'white',
        borderWidth: 2,
        radius: 8,
        label: {
          display: true,
          content: point.annotation,
          position: 'top',
          backgroundColor: 'rgba(255, 99, 132, 0.9)',
          color: 'white',
          font: {
            size: 11,
          },
          padding: 6,
        },
      };
    }
  });

  const chartData = {
    labels,
    datasets,
  };

  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        position: 'top',
      },
      tooltip: {
        mode: 'index',
        intersect: false,
        callbacks: {
          afterLabel: (context) => {
            const dataPoint = data[context.dataIndex];
            if (dataPoint.annotation) {
              return `📌 ${dataPoint.annotation}`;
            }
            if (targetVelocity !== undefined) {
              const diff = dataPoint.value - targetVelocity;
              const status = diff >= 0 ? 'above' : 'below';
              return `${Math.abs(diff).toFixed(1)}h ${status} target`;
            }
            return '';
          },
        },
      },
      annotation: {
        annotations,
      },
    },
    scales: {
      y: {
        beginAtZero: true,
        title: {
          display: true,
          text: 'Hours Completed',
          font: {
            size: 14,
            weight: 'bold',
          },
        },
        ticks: {
          callback: (value) => `${value}h`,
        },
      },
      x: {
        title: {
          display: true,
          text: 'Sprint / Week',
          font: {
            size: 14,
            weight: 'bold',
          },
        },
      },
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false,
    },
  };

  return (
    <div style={{ height: `${height}px` }}>
      <Line data={chartData} options={options} />
    </div>
  );
};

VelocityChart.displayName = 'VelocityChart';

export default React.memo(VelocityChart);
