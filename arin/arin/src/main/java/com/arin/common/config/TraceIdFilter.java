// 추가: TraceIdFilter
package com.arin.common.config;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.util.UUID;

@Component
public class TraceIdFilter implements Filter {
    public static final String TRACE_ID = "X-Trace-Id";
    @Override public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain) throws IOException, ServletException {
        HttpServletRequest r = (HttpServletRequest) req;
        HttpServletResponse w = (HttpServletResponse) res;
        String tid = r.getHeader(TRACE_ID);
        if (tid == null || tid.isBlank()) tid = UUID.randomUUID().toString();
        MDC.put(TRACE_ID, tid);
        try {
            w.setHeader(TRACE_ID, tid);
            chain.doFilter(req, res);
        } finally {
            MDC.remove(TRACE_ID);
        }
    }
}
