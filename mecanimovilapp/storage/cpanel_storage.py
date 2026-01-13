"""
Storage backend personalizado para subir archivos a cPanel vía FTP.

Este backend permite que Django suba archivos directamente a un servidor cPanel
usando FTP, evitando el problema del sistema de archivos efímero en Render.

Uso:
    En settings.py (o variables de entorno en Render):
    DEFAULT_FILE_STORAGE = 'mecanimovilapp.storage.cpanel_storage.CPanelStorage'
    
    Variables de entorno (NUNCA hardcodear credenciales en el código):
    CPANEL_FTP_HOST=ftp.mecanimovil.cl
    CPANEL_FTP_USER=mecanimovil-media@mecanimovil.cl
    CPANEL_FTP_PASSWORD=tu_contraseña_segura
    CPANEL_FTP_ROOT=/public_html/images/mecanimovil-app-media  # Ruta absoluta en el servidor
    CPANEL_MEDIA_URL=https://mecanimovil.cl/images/mecanimovil-app-media/  # URL pública
"""

import ftplib
import os
import tempfile
from django.core.files.storage import Storage
from django.core.files.base import File
from django.conf import settings
from django.utils.deconstruct import deconstructible
import logging

logger = logging.getLogger(__name__)


@deconstructible
class CPanelStorage(Storage):
    """
    Storage backend que sube archivos a cPanel usando FTP.
    
    Los archivos se suben temporalmente a disco local, luego se transfieren
    vía FTP al servidor cPanel, y finalmente se eliminan del disco local.
    """
    
    def __init__(self, location=None, base_url=None):
        # Normalizar la ruta: si no empieza con /, se asume que es relativa al directorio de la cuenta FTP
        # El valor por defecto debe venir de las variables de entorno, no hardcodeado
        raw_location = location or getattr(settings, 'CPANEL_FTP_ROOT', None)
        if not raw_location:
            raise ValueError(
                "CPANEL_FTP_ROOT no está configurado. "
                "Configura la variable de entorno CPANEL_FTP_ROOT con la ruta en el servidor cPanel. "
                "Ejemplo: 'public_html/images/mecanimovil-app-media' o '/public_html/images/mecanimovil-app-media'"
            )
        # Si la ruta no empieza con /, mantenerla relativa (para cuentas FTP restringidas)
        # Si empieza con /, usar como ruta absoluta
        self.location = raw_location
        self.base_url = base_url or getattr(settings, 'CPANEL_MEDIA_URL', '')
        self.ftp_host = getattr(settings, 'CPANEL_FTP_HOST', None)
        self.ftp_user = getattr(settings, 'CPANEL_FTP_USER', None)
        self.ftp_password = getattr(settings, 'CPANEL_FTP_PASSWORD', None)
        
        # Log para debugging
        logger.info(f"🔍 [CPanelStorage.__init__] location: {self.location}")
        logger.info(f"🔍 [CPanelStorage.__init__] base_url: {self.base_url}")
        logger.info(f"🔍 [CPanelStorage.__init__] ftp_host: {self.ftp_host}")
        
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            logger.warning("⚠️ [CPanelStorage] Configuración FTP incompleta. Verifica CPANEL_FTP_* en settings.")
        
        if not self.base_url:
            logger.warning("⚠️ [CPanelStorage] CPANEL_MEDIA_URL no está configurado. Las URLs se construirán manualmente en el serializer.")
    
    def _connect_ftp(self):
        """Establece conexión FTP con el servidor cPanel."""
        try:
            ftp = ftplib.FTP(self.ftp_host)
            ftp.login(self.ftp_user, self.ftp_password)
            ftp.set_pasv(True)  # Modo pasivo (recomendado para la mayoría de servidores)
            
            # Verificar el directorio actual después de conectarse
            try:
                current_dir = ftp.pwd()
                logger.warning(f"🔍 [CPanelStorage._connect_ftp] Directorio actual después de conexión: {current_dir}")
            except:
                logger.warning(f"🔍 [CPanelStorage._connect_ftp] No se pudo obtener directorio actual")
            
            return ftp
        except Exception as e:
            logger.error(f"❌ [CPanelStorage] Error conectando a FTP: {e}")
            raise
    
    def _ensure_directory_exists(self, ftp, remote_path):
        """
        Asegura que el directorio remoto existe, creándolo si es necesario.
        
        Args:
            ftp: Conexión FTP activa
            remote_path: Ruta del archivo remoto (puede ser absoluta o relativa)
        """
        # Obtener el directorio del archivo
        directory = os.path.dirname(remote_path)
        
        # Si el directorio está vacío o es solo el nombre del archivo, no hacer nada
        if not directory or directory == '.' or directory == '/':
            return
        
        # Determinar si es ruta absoluta o relativa
        is_absolute = directory.startswith('/')
        
        # Dividir la ruta en partes
        if is_absolute:
            parts = directory.strip('/').split('/')
            current_path = ''
        else:
            parts = directory.split('/')
            current_path = ''
        
        # Crear cada directorio en la ruta si no existe
        for part in parts:
            if not part:  # Saltar partes vacías
                continue
                
            if is_absolute:
                current_path = current_path + '/' + part if current_path else '/' + part
            else:
                current_path = current_path + '/' + part if current_path else part
            
            try:
                # Intentar cambiar al directorio
                ftp.cwd(current_path)
            except ftplib.error_perm:
                # Si no existe, crearlo
                try:
                    ftp.mkd(current_path)
                    logger.info(f"📁 [CPanelStorage] Directorio creado: {current_path}")
                    # Intentar cambiar al directorio recién creado
                    ftp.cwd(current_path)
                except ftplib.error_perm as e:
                    # Puede que ya exista o haya un problema de permisos
                    logger.warning(f"⚠️ [CPanelStorage] No se pudo crear directorio {current_path}: {e}")
                    # Intentar cambiar de nuevo por si acaso
                    try:
                        ftp.cwd(current_path)
                    except:
                        pass
    
    def _save(self, name, content):
        """
        Guarda un archivo en el servidor cPanel vía FTP.
        
        Args:
            name: Nombre del archivo (ej: 'vehiculos/vehicle_123.jpg')
            content: Objeto File de Django con el contenido
            
        Returns:
            str: Nombre del archivo guardado
        """
        logger.warning(f"🔄 [CPanelStorage._save] INICIANDO - Guardando archivo: {name}")
        logger.warning(f"🔄 [CPanelStorage._save] location: {self.location}")
        logger.warning(f"🔄 [CPanelStorage._save] ftp_host: {self.ftp_host}")
        logger.warning(f"🔄 [CPanelStorage._save] ftp_user: {self.ftp_user}")
        
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            logger.error("❌ [CPanelStorage._save] Configuración FTP incompleta. No se puede guardar archivo.")
            raise ValueError("Configuración FTP incompleta. Verifica CPANEL_FTP_* en settings.")
        
        # Construir la ruta completa en el servidor
        # Si location es absoluta (empieza con /), usar join normal
        # Si location es relativa, también usar join normal (funciona para ambos casos)
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        # Normalizar: eliminar dobles slashes pero mantener el / inicial si existe
        if remote_path.startswith('//'):
            remote_path = '/' + remote_path.lstrip('/')
        
        logger.warning(f"🔄 [CPanelStorage._save] Ruta remota construida: {remote_path}")
        
        # Guardar temporalmente en disco local
        temp_file = None
        try:
            # Crear archivo temporal
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            
            # Escribir contenido al archivo temporal
            for chunk in content.chunks():
                temp_file.write(chunk)
            temp_file.close()
            
            # Subir vía FTP
            ftp = None
            try:
                ftp = self._connect_ftp()
                
                # Verificar el directorio actual
                try:
                    current_dir = ftp.pwd()
                    logger.warning(f"🔍 [CPanelStorage._save] Directorio actual FTP: {current_dir}")
                except:
                    current_dir = None
                
                # Simplificar la navegación: trabajar con la ruta relativa desde donde estemos
                # Si location incluye public_html/, removerlo de la ruta porque navegaremos manualmente
                if remote_path.startswith('public_html/'):
                    remote_path = remote_path.replace('public_html/', '', 1)
                    logger.warning(f"🔍 [CPanelStorage._save] Ruta ajustada (removido public_html/): {remote_path}")
                
                # Navegar a public_html si no estamos ahí
                try:
                    current = ftp.pwd()
                    logger.warning(f"🔍 [CPanelStorage._save] Directorio actual: {current}")
                    
                    # Si no estamos en public_html, intentar navegar
                    if 'public_html' not in current:
                        try:
                            ftp.cwd('public_html')
                            logger.warning(f"✅ [CPanelStorage._save] Navegado a public_html/")
                        except ftplib.error_perm:
                            # Si no existe public_html, puede que estemos en la raíz de la cuenta FTP
                            # Intentar navegar directamente a images
                            logger.warning(f"⚠️ [CPanelStorage._save] public_html/ no encontrado, intentando navegar directamente")
                except:
                    # Si no podemos obtener el directorio actual, intentar navegar a public_html
                    try:
                        ftp.cwd('public_html')
                        logger.warning(f"✅ [CPanelStorage._save] Navegado a public_html/")
                    except:
                        pass
                
                # Navegar al directorio del archivo (images/mecanimovil-app-media)
                remote_dir = os.path.dirname(remote_path)
                if remote_dir:
                    logger.warning(f"🔍 [CPanelStorage._save] Navegando a directorio: {remote_dir}")
                    dir_parts = remote_dir.split('/')
                    dir_parts = [p for p in dir_parts if p]  # Eliminar partes vacías
                    logger.warning(f"🔍 [CPanelStorage._save] Partes del directorio: {dir_parts}")
                    
                    for part in dir_parts:
                        logger.warning(f"🔍 [CPanelStorage._save] Intentando navegar a: '{part}'")
                        
                        # PRIMERO: Listar directorios actuales para ver qué existe
                        try:
                            current_dir = ftp.pwd()
                            logger.warning(f"🔍 [CPanelStorage._save] Directorio actual antes de navegar: {current_dir}")
                            files_and_dirs = ftp.nlst()
                            logger.warning(f"🔍 [CPanelStorage._save] Contenido del directorio actual: {files_and_dirs}")
                            
                            # Buscar el directorio (puede tener diferente capitalización)
                            matching_dir = None
                            for item in files_and_dirs:
                                if item.lower() == part.lower() or item == part:
                                    matching_dir = item
                                    break
                            
                            if matching_dir and matching_dir != part:
                                logger.warning(f"⚠️ [CPanelStorage._save] Directorio encontrado con nombre diferente: '{matching_dir}' (buscando '{part}')")
                                part = matching_dir
                        except Exception as e:
                            logger.warning(f"⚠️ [CPanelStorage._save] No se pudo listar directorio: {e}")
                        
                        try:
                            # Intentar navegar (el directorio ya existe)
                            ftp.cwd(part)
                            logger.warning(f"✅ [CPanelStorage._save] Navegado a: {part}")
                        except ftplib.error_perm as e:
                            # Si no existe, intentar crearlo
                            logger.warning(f"⚠️ [CPanelStorage._save] Directorio '{part}' no encontrado, intentando crear...")
                            try:
                                ftp.mkd(part)
                                logger.warning(f"✅ [CPanelStorage._save] Directorio '{part}' creado")
                                ftp.cwd(part)
                                logger.warning(f"✅ [CPanelStorage._save] Navegado a directorio creado: {part}")
                            except Exception as e2:
                                logger.error(f"❌ [CPanelStorage._save] Error con directorio '{part}': {e2}")
                                # Listar de nuevo para debug
                                try:
                                    current_dir = ftp.pwd()
                                    files_and_dirs = ftp.nlst()
                                    logger.error(f"❌ [CPanelStorage._save] Directorio actual: {current_dir}")
                                    logger.error(f"❌ [CPanelStorage._save] Directorios disponibles: {files_and_dirs}")
                                except:
                                    pass
                                raise
                else:
                    logger.warning(f"🔍 [CPanelStorage._save] No hay subdirectorio, subiendo a directorio actual")
                
                # Verificar el directorio actual antes de subir
                try:
                    final_dir = ftp.pwd()
                    logger.warning(f"🔍 [CPanelStorage._save] Directorio final antes de subir: {final_dir}")
                except:
                    final_dir = "No se pudo obtener"
                    logger.warning(f"⚠️ [CPanelStorage._save] No se pudo obtener directorio final")
                
                # Subir el archivo
                filename = os.path.basename(remote_path)
                logger.warning(f"🔄 [CPanelStorage._save] Subiendo archivo vía FTP: {filename}")
                logger.warning(f"🔄 [CPanelStorage._save] Directorio destino: {remote_dir or 'raíz'}")
                logger.warning(f"🔄 [CPanelStorage._save] Ruta completa remota: {remote_path}")
                
                try:
                    with open(temp_file.name, 'rb') as f:
                        result = ftp.storbinary(f'STOR {filename}', f)
                        logger.warning(f"🔍 [CPanelStorage._save] Resultado de STOR: {result}")
                    
                    # Verificar que el archivo existe después de subirlo
                    try:
                        ftp.retrbinary(f'RETR {filename}', lambda x: None)
                        logger.warning(f"✅ [CPanelStorage._save] ARCHIVO VERIFICADO - Existe en servidor: {filename}")
                    except Exception as e:
                        logger.error(f"❌ [CPanelStorage._save] ARCHIVO NO VERIFICADO - Error al verificar: {e}")
                    
                    # Listar archivos en el directorio actual para confirmar
                    try:
                        files = ftp.nlst()
                        logger.warning(f"🔍 [CPanelStorage._save] Archivos en directorio actual: {files[:10]}")  # Primeros 10
                        if filename in files:
                            logger.warning(f"✅ [CPanelStorage._save] ARCHIVO ENCONTRADO en listado: {filename}")
                        else:
                            logger.error(f"❌ [CPanelStorage._save] ARCHIVO NO ENCONTRADO en listado del directorio")
                    except Exception as e:
                        logger.warning(f"⚠️ [CPanelStorage._save] No se pudo listar archivos: {e}")
                    
                    logger.warning(f"✅ [CPanelStorage._save] ARCHIVO SUBIDO EXITOSAMENTE: {remote_path}")
                    logger.warning(f"✅ [CPanelStorage._save] Archivo disponible en: https://www.mecanimovil.cl/images/mecanimovil-app-media/{name}")
                except Exception as e:
                    logger.error(f"❌ [CPanelStorage._save] ERROR al subir archivo: {e}")
                    raise
                
            finally:
                if ftp:
                    try:
                        ftp.quit()
                    except:
                        ftp.close()
            
            return name
            
        finally:
            # Eliminar archivo temporal
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
    
    def _open(self, name, mode='rb'):
        """
        Abre un archivo desde el servidor cPanel.
        
        Nota: Este método descarga el archivo temporalmente para leerlo.
        En producción, los archivos se sirven directamente desde cPanel vía HTTP.
        """
        # En producción, los archivos se sirven directamente desde cPanel
        # Este método solo se usa en casos especiales
        raise NotImplementedError("Los archivos se sirven directamente desde cPanel vía HTTP")
    
    def exists(self, name):
        """
        Verifica si un archivo existe en el servidor cPanel.
        
        Args:
            name: Nombre del archivo
            
        Returns:
            bool: True si existe, False si no
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            return False
        
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        filename = os.path.basename(remote_path)
        
        ftp = None
        try:
            ftp = self._connect_ftp()
            
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except:
                    return False
            
            # Listar archivos en el directorio
            files = ftp.nlst()
            return filename in files
            
        except Exception as e:
            logger.warning(f"⚠️ [CPanelStorage] Error verificando existencia de {name}: {e}")
            return False
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
    
    def url(self, name):
        """
        Retorna la URL pública del archivo en cPanel.
        
        Args:
            name: Nombre del archivo (ej: 'vehiculos/vehicle_xxx.jpg')
            
        Returns:
            str: URL completa del archivo
        """
        # Si no hay base_url configurado, intentar obtenerlo de settings
        if not self.base_url:
            from django.conf import settings
            self.base_url = getattr(settings, 'CPANEL_MEDIA_URL', '')
            logger.debug(f"🔍 [CPanelStorage.url] base_url obtenido de settings: {self.base_url}")
        
        if not self.base_url:
            logger.warning(f"⚠️ [CPanelStorage.url] base_url no configurado para archivo: {name}")
            # Retornar None para que Django use el comportamiento por defecto
            # El serializer manejará esto y construirá la URL manualmente
            return None
        
        # Asegurar que base_url termina con /
        base = self.base_url.rstrip('/') + '/'
        
        # Construir URL completa
        # name ya viene como 'vehiculos/vehicle_xxx.jpg' (sin /media/)
        url = base + name.lstrip('/')
        logger.info(f"✅ [CPanelStorage.url] URL construida para {name}: {url}")
        return url
    
    def delete(self, name):
        """
        Elimina un archivo del servidor cPanel.
        
        Args:
            name: Nombre del archivo a eliminar
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            logger.error("❌ [CPanelStorage] Configuración FTP incompleta. No se puede eliminar archivo.")
            return
        
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        filename = os.path.basename(remote_path)
        
        ftp = None
        try:
            ftp = self._connect_ftp()
            
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except:
                    logger.warning(f"⚠️ [CPanelStorage] No se pudo cambiar al directorio: {remote_dir}")
                    return
            
            # Eliminar archivo
            ftp.delete(filename)
            logger.info(f"🗑️ [CPanelStorage] Archivo eliminado: {remote_path}")
            
        except Exception as e:
            logger.error(f"❌ [CPanelStorage] Error eliminando archivo {name}: {e}")
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
    
    def size(self, name):
        """
        Obtiene el tamaño de un archivo en el servidor cPanel.
        
        Args:
            name: Nombre del archivo
            
        Returns:
            int: Tamaño en bytes, o None si no se puede obtener
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            return None
        
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        filename = os.path.basename(remote_path)
        
        ftp = None
        try:
            ftp = self._connect_ftp()
            
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except:
                    return None
            
            # Obtener tamaño del archivo
            size = ftp.size(filename)
            return size
            
        except Exception as e:
            logger.warning(f"⚠️ [CPanelStorage] Error obteniendo tamaño de {name}: {e}")
            return None
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
