import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import { type Incident, type Service } from '../utils/api';

interface ServiceGraphProps {
  services: Service[];
  incidents: Incident[];
  onNodeClick?: (serviceName: string) => void;
}

export function ServiceGraph({ services, incidents, onNodeClick }: ServiceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    if (!svgRef.current || !services.length) return;

    const width = 600;
    const height = 400;

    // Clear previous
    d3.select(svgRef.current).selectAll('*').remove();

    const svg = d3.select(svgRef.current)
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .style('background', 'transparent');

    // Build nodes and links from service dependencies
    const nodes = services.map(s => ({ 
      id: s.name, 
      critical: s.is_critical || false,
      hasIncident: incidents.some(i => i.service_name === s.name),
      severity: incidents.find(i => i.service_name === s.name)?.severity || null
    }));
    
    const links = services.flatMap(s =>
      (s.dependencies || []).map(d => ({ 
        source: s.name, 
        target: d 
      }))
    );

    // Filter out links where target doesn't exist
    const validLinks = links.filter(l => 
      nodes.some(n => n.id === l.source) && nodes.some(n => n.id === l.target)
    );

    const simulation = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(validLinks).id((d: any) => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(40));

    // Links
    const link = svg.append('g')
      .selectAll('line')
      .data(validLinks)
      .enter()
      .append('line')
      .attr('stroke', '#cbd5e1')
      .attr('stroke-opacity', 0.8)
      .attr('stroke-width', 2);

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

    nodeGroup.append('circle')
      .attr('r', (d: any) => d.critical ? 28 : 22)
      .attr('fill', (d: any) => {
        if (d.severity === 'P0') return '#ef4444';
        if (d.severity === 'P1') return '#f97316';
        if (d.hasIncident) return '#eab308';
        return '#3b82f6';
      })
      .attr('stroke', '#fff')
      .attr('stroke-width', 3);

    nodeGroup.append('text')
      .text((d: any) => d.id)
      .attr('text-anchor', 'middle')
      .attr('dy', 5)
      .attr('font-size', 10)
      .attr('fill', '#fff')
      .attr('font-weight', 'bold')
      .style('text-shadow', '0 1px 3px rgba(0,0,0,0.5)');

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
    };

  }, [services, incidents, onNodeClick]);

  return (
    <div ref={containerRef} className="bg-white dark:bg-dark-surface rounded-xl shadow-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold dark:text-dark-text">Service Dependency Graph</h3>
        <div className="flex gap-4 text-xs dark:text-dark-muted">
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-red-500 mr-1"></span>P0</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-orange-500 mr-1"></span>P1</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-yellow-500 mr-1"></span>Has Incident</span>
          <span className="flex items-center"><span className="w-3 h-3 rounded-full bg-blue-500 mr-1"></span>Healthy</span>
        </div>
      </div>
      <svg ref={svgRef} className="w-full h-96"></svg>
    </div>
  );
}
