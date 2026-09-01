import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { type Incident, type Service } from '../utils/api';
import { motion } from 'framer-motion';

interface ServiceGraphProps {
  services: Service[];
  incidents: Incident[];
  onNodeClick?: (serviceName: string) => void;
}

export function ServiceGraph({ services, incidents, onNodeClick }: ServiceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 400 });

  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        setDimensions({ width: width || 600, height: Math.min(width * 0.6, 500) });
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  useEffect(() => {
    if (!svgRef.current || !services.length) return;

    const { width, height } = dimensions;
    d3.select(svgRef.current).selectAll('*').remove();

    const svg = d3.select(svgRef.current)
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .style('background', 'transparent');

    // Gradient definitions
    const defs = svg.append('defs');
    
    defs.append('filter')
      .attr('id', 'glow')
      .append('feDropShadow')
      .attr('dx', 0)
      .attr('dy', 0)
      .attr('stdDeviation', 4)
      .attr('flood-color', '#6C63FF')
      .attr('flood-opacity', 0.3);

    const nodes = services.map(s => ({ 
      id: s.name, 
      critical: s.is_critical || false,
      hasIncident: incidents.some(i => i.service_name === s.name),
      severity: incidents.find(i => i.service_name === s.name)?.severity || null
    }));
    
    const links = services.flatMap(s =>
      (s.dependencies || []).map(d => ({ source: s.name, target: d }))
    );

    const simulation = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(links).id((d: any) => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(40));

    // Links
    const link = svg.append('g')
      .selectAll('line')
      .data(links)
      .enter()
      .append('line')
      .attr('stroke', '#30363D')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', (d: any) => {
        const source = nodes.find((n: any) => n.id === d.source);
        const target = nodes.find((n: any) => n.id === d.target);
        return source?.hasIncident || target?.hasIncident ? '4,4' : 'none';
      });

    // Nodes
    const nodeGroup = svg.append('g')
      .selectAll('g')
      .data(nodes)
      .enter()
      .append('g')
      .style('cursor', 'pointer')
      .on('click', (_event, d: any) => {
        if (onNodeClick) onNodeClick(d.id);
      })
      .call(d3.drag<any, any>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
      );

    // Node circles with glow
    nodeGroup.append('circle')
      .attr('r', (d: any) => d.critical ? 30 : 24)
      .attr('fill', (d: any) => {
        if (d.severity === 'P0') return '#FF4444';
        if (d.severity === 'P1') return '#FF8800';
        if (d.hasIncident) return '#FFD700';
        return '#6C63FF';
      })
      .attr('stroke', (d: any) => d.hasIncident ? '#FFD700' : '#1A1A3E')
      .attr('stroke-width', 3)
      .attr('filter', (d: any) => d.hasIncident ? 'url(#glow)' : null);

    // Pulse ring for nodes with incidents
    nodeGroup.filter((d: any) => d.hasIncident)
      .append('circle')
      .attr('r', (d: any) => d.critical ? 36 : 30)
      .attr('fill', 'none')
      .attr('stroke', (d: any) => {
        if (d.severity === 'P0') return '#FF4444';
        if (d.severity === 'P1') return '#FF8800';
        return '#FFD700';
      })
      .attr('stroke-width', 2)
      .attr('opacity', 0.6)
      .style('animation', 'pulse 2s ease-out infinite');

    // Node labels
    nodeGroup.append('text')
      .text((d: any) => d.id)
      .attr('text-anchor', 'middle')
      .attr('dy', 5)
      .attr('font-size', 10)
      .attr('fill', '#fff')
      .attr('font-weight', 'bold')
      .style('text-shadow', '0 1px 3px rgba(0,0,0,0.5)');

    // Tooltips on hover
    const tooltip = d3.select('body').append('div')
      .style('position', 'absolute')
      .style('background', '#161B22')
      .style('color', '#E6EDF3')
      .style('padding', '8px 12px')
      .style('border-radius', '8px')
      .style('font-size', '12px')
      .style('pointer-events', 'none')
      .style('opacity', 0)
      .style('border', '1px solid #30363D')
      .style('box-shadow', '0 4px 12px rgba(0,0,0,0.5)')
      .style('transition', 'opacity 0.2s');

    nodeGroup
      .on('mouseover', (event, d: any) => {
        const incident = incidents.find(i => i.service_name === d.id);
        let html = `<strong>${d.id}</strong><br/>`;
        if (incident) {
          html += `⚠️ ${incident.severity} - ${incident.title}<br/>`;
          html += `Status: ${incident.status}`;
        } else {
          html += '✅ Healthy';
        }
        tooltip
          .style('opacity', 1)
          .html(html)
          .style('left', (event.pageX + 10) + 'px')
          .style('top', (event.pageY - 10) + 'px');
      })
      .on('mousemove', (event) => {
        tooltip
          .style('left', (event.pageX + 10) + 'px')
          .style('top', (event.pageY - 10) + 'px');
      })
      .on('mouseout', () => {
        tooltip.style('opacity', 0);
      });

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      nodeGroup
        .attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
      tooltip.remove();
    };

  }, [services, incidents, dimensions, onNodeClick]);

  return (
    <div ref={containerRef} className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold dark:text-dark-text">Service Dependency Graph</h3>
        <div className="flex gap-4 text-xs dark:text-dark-muted">
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-severity-critical mr-1"></span>P0</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-severity-high mr-1"></span>P1</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-yellow-500 mr-1"></span>Has Incident</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-primary-500 mr-1"></span>Healthy</span>
        </div>
      </div>
      <svg ref={svgRef} className="w-full"></svg>
    </div>
  );
}