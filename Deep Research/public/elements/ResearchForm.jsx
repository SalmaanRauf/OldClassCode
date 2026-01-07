import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import React, { useState } from 'react';

export default function ResearchForm() {
    const [values, setValues] = useState({
        sector: props.sector || 'general',
        company: props.company || '',
        signals: props.signals || '',
        service_lines: props.service_lines || '',
        geography: props.geography || '',
        min_value: props.min_value || '',
        time_window: props.time_window || '',
        max_opportunities: props.max_opportunities || '10',
        other_context: props.other_context || ''
    });

    const sectors = props.sectors || [
        { value: 'defense', label: 'Defense' },
        { value: 'financial_services', label: 'Financial Services' },
        { value: 'healthcare', label: 'Healthcare' },
        { value: 'energy', label: 'Energy' },
        { value: 'technology', label: 'Technology' },
        { value: 'general', label: 'General' }
    ];

    const handleChange = (id, val) => {
        setValues((v) => ({ ...v, [id]: val }));
    };

    return (
        <Card className="w-full max-w-2xl mt-4">
            <CardHeader>
                <CardTitle>🔬 Research Parameters</CardTitle>
                <CardDescription>Configure your deep research query</CardDescription>
            </CardHeader>

            <CardContent className="grid grid-cols-2 gap-4">
                {/* Sector Dropdown */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="sector">Sector / Industry</Label>
                    <Select value={values.sector} onValueChange={(val) => handleChange('sector', val)}>
                        <SelectTrigger id="sector">
                            <SelectValue placeholder="Select sector" />
                        </SelectTrigger>
                        <SelectContent>
                            {sectors.map((s) => (
                                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                {/* Company or Topic */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="company">Company or Topic</Label>
                    <Input
                        id="company"
                        placeholder="e.g., Lockheed Martin"
                        value={values.company}
                        onChange={(e) => handleChange('company', e.target.value)}
                    />
                </div>

                {/* Signals */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="signals">Signals to Detect</Label>
                    <Input
                        id="signals"
                        placeholder="e.g., CMMC, IV&V"
                        value={values.signals}
                        onChange={(e) => handleChange('signals', e.target.value)}
                    />
                </div>

                {/* Service Lines */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="service_lines">Service Lines</Label>
                    <Input
                        id="service_lines"
                        placeholder="e.g., Model Validation"
                        value={values.service_lines}
                        onChange={(e) => handleChange('service_lines', e.target.value)}
                    />
                </div>

                {/* Geography */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="geography">Geography</Label>
                    <Input
                        id="geography"
                        placeholder="e.g., CONUS, Global"
                        value={values.geography}
                        onChange={(e) => handleChange('geography', e.target.value)}
                    />
                </div>

                {/* Min Value */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="min_value">Min Value USD</Label>
                    <Input
                        id="min_value"
                        placeholder="e.g., 10M"
                        value={values.min_value}
                        onChange={(e) => handleChange('min_value', e.target.value)}
                    />
                </div>

                {/* Time Window */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="time_window">Time Window</Label>
                    <Input
                        id="time_window"
                        placeholder="e.g., Last 90 days"
                        value={values.time_window}
                        onChange={(e) => handleChange('time_window', e.target.value)}
                    />
                </div>

                {/* Max Opportunities */}
                <div className="flex flex-col gap-2">
                    <Label htmlFor="max_opportunities">Max Opportunities</Label>
                    <Input
                        id="max_opportunities"
                        placeholder="e.g., 10"
                        value={values.max_opportunities}
                        onChange={(e) => handleChange('max_opportunities', e.target.value)}
                    />
                </div>

                {/* Other Context - spans full width */}
                <div className="flex flex-col gap-2 col-span-2">
                    <Label htmlFor="other_context">Other Context (optional)</Label>
                    <Textarea
                        id="other_context"
                        placeholder="Any additional context, focus areas, or special instructions..."
                        value={values.other_context}
                        onChange={(e) => handleChange('other_context', e.target.value)}
                        rows={3}
                    />
                </div>
            </CardContent>

            <CardFooter className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => cancelElement()}>
                    Cancel
                </Button>
                <Button onClick={() => submitElement(values)}>
                    🚀 Generate Prompt
                </Button>
            </CardFooter>
        </Card>
    );
}
