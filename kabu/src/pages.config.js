/**
 * pages.config.js - Page routing configuration
 * 
 * This file is AUTO-GENERATED. Do not add imports or modify PAGES manually.
 * Pages are auto-registered when you create files in the ./pages/ folder.
 * 
 * THE ONLY EDITABLE VALUE: mainPage
 * This controls which page is the landing page (shown when users visit the app).
 */
import Landing from './pages/Landing';
import Home from './pages/Home';
import GenerateReport from './pages/GenerateReport';
import ReportViewer from './pages/ReportViewer';
import CompanyDetail from './pages/CompanyDetail';
import DirectorCorrelation from './pages/DirectorCorrelation';
import Query from './pages/Query';
import __Layout from './Layout.jsx';

export const PAGES = {
    "Landing": Landing,
    "Home": Home,
    "GenerateReport": GenerateReport,
    "Viewer": ReportViewer,
    "CompanyDetail": CompanyDetail,
    "DirectorMap": DirectorCorrelation,
    "Query": Query,
}

export const pagesConfig = {
    mainPage: "Landing",
    Pages: PAGES,
    Layout: __Layout,
};
